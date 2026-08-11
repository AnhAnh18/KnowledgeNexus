"""Production composition root for the bounded Root 1 subtree crawler.

This module only wires approved infrastructure seams.  It deliberately does
not implement HTTP, pagination, retry, checkpoint, or raw-store behavior.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from knowledgenexus.foundation.domain.models.confluence_page_observation import AttachmentMetadataRequest
from knowledgenexus.foundation.domain.rules.confluence_page_observations import parse_attachment_metadata_window
from knowledgenexus.foundation.domain.models.media_materialization import ConfluenceAttachmentObservation
from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_attachment_body import FetchAndStoreConfluenceAttachmentBody
from knowledgenexus.foundation.application.use_cases.process_confluence_media_attachment import ProcessConfluenceMediaAttachment
from knowledgenexus.foundation.domain.models.media_body_materialization import MediaBodyStoreBudget
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawAttachmentStore
from knowledgenexus.foundation.infrastructure.processors.media_attachment_processors import DrawioProcessor

from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_inventory_adapter import (
    ConfluenceDataCenterInventoryAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_adapter import (
    ConfluenceDataCenterPageAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_observation_adapter import (
    ConfluenceDataCenterPageObservationAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_attachment_body_adapter import (
    ConfluenceDataCenterAttachmentBodyAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import (
    ConfluenceRetryExecutorProfile,
    RetryingConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_generation_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
)


BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"


@dataclass(frozen=True, repr=False)
class LiveSubtreeComposition:
    """Concrete production dependencies for inventory and page capture."""

    transport: object
    inventory_adapter: ConfluenceDataCenterInventoryAdapter
    page_adapter: ConfluenceDataCenterPageAdapter
    checkpoint_run_port: SqliteConfluenceCheckpointRunPort
    raw_page_store: ConfluenceRawPageGenerationStore
    retry_profile: ConfluenceRetryExecutorProfile
    http_inner: object

    def __repr__(self) -> str:
        return "LiveSubtreeComposition()"

    def inventory_use_case(self, *, max_search_pages: int) -> ExecuteDurableConfluenceInventory:
        """Bind the durable inventory loop to this production adapter factory."""
        if type(max_search_pages) is not int or max_search_pages <= 0:
            raise ValueError("max_search_pages must be positive")
        return ExecuteDurableConfluenceInventory(
            checkpoint_run_port=self.checkpoint_run_port,
            inventory_transport_factory=lambda activation: RetryingConfluenceHttpTransport(
                inner=self.http_inner, profile=self.retry_profile,
                monotonic_clock=time.monotonic, sleeper=time.sleep,
                attempt_reserver=activation,
            ),
            inventory_window_port_factory=lambda transport: ConfluenceDataCenterInventoryAdapter(
                transport=transport, max_search_pages=max_search_pages
            ),
        )

    def attachment_components(self, *, attachment_root: Path, budget: MediaBodyStoreBudget, attachment_page_size: int = 100, max_attachment_pages: int = 100, transport: object | None = None):
        """Return concrete metadata, immutable-body and Draw.io processors."""
        if not isinstance(attachment_root, Path) or not attachment_root.is_absolute():
            raise ValueError("attachment_root must be absolute")
        if type(attachment_page_size) is not int or attachment_page_size <= 0:
            raise ValueError("attachment_page_size must be positive")
        if type(max_attachment_pages) is not int or max_attachment_pages <= 0:
            raise ValueError("max_attachment_pages must be positive")
        selected_transport = self.transport if transport is None else transport
        observer = _LiveAttachmentObserver(selected_transport, attachment_page_size, max_attachment_pages)
        store = ConfluenceRawAttachmentStore(data_root=attachment_root, budget=budget)
        materializer = FetchAndStoreConfluenceAttachmentBody(
            body_fetcher=ConfluenceDataCenterAttachmentBodyAdapter(transport=selected_transport),
            raw_attachment_store=store, budget=budget,
        )
        processor = ProcessConfluenceMediaAttachment(drawio_processor=DrawioProcessor())
        return observer, materializer, processor


def compose_live_subtree(
    *,
    raw_root: Path,
    checkpoint_workspace: Path,
    reliability_profile: Mapping[str, object],
    max_search_pages: int,
    base_url: str | None = None,
    personal_access_token: str | None = None,
) -> LiveSubtreeComposition:
    """Construct approved live adapters without exposing credential values.

    Credentials default to environment variables and are never retained in the
    returned object or included in exception text.
    """
    if not isinstance(raw_root, Path) or not raw_root.is_absolute():
        raise ValueError("raw_root must be absolute")
    if not isinstance(checkpoint_workspace, Path) or not checkpoint_workspace.is_absolute():
        raise ValueError("checkpoint_workspace must be absolute")
    if type(max_search_pages) is not int or max_search_pages <= 0:
        raise ValueError("max_search_pages must be positive")
    if not isinstance(reliability_profile, Mapping):
        raise TypeError("reliability_profile must be a mapping")
    endpoint = base_url if base_url is not None else os.environ.get(BASE_URL_ENV)
    token = personal_access_token if personal_access_token is not None else os.environ.get(PAT_ENV)
    if type(endpoint) is not str or not endpoint or type(token) is not str or not token:
        raise ValueError("production credentials are required")
    # The approved B1 transport owns URL construction and credential headers.
    inner = UrllibConfluenceHttpTransport(
        base_url=endpoint,
        personal_access_token=token,
    )
    profile = ConfluenceRetryExecutorProfile.from_mapping(reliability_profile)
    transport = RetryingConfluenceHttpTransport(
        inner=inner,
        profile=profile,
        monotonic_clock=time.monotonic,
        sleeper=time.sleep,
    )
    return LiveSubtreeComposition(
        transport=transport,
        inventory_adapter=ConfluenceDataCenterInventoryAdapter(
            transport=transport,
            max_search_pages=max_search_pages,
        ),
        page_adapter=ConfluenceDataCenterPageAdapter(transport=transport),
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
        retry_profile=profile,
        http_inner=inner,
    )


class _LiveAttachmentObserver:
    def __init__(self, transport: object, page_size: int, max_pages: int) -> None:
        self._adapter = ConfluenceDataCenterPageObservationAdapter(transport=transport)
        self._page_size, self._max_pages = page_size, max_pages

    def list_attachments(self, page_id: str) -> tuple[ConfluenceAttachmentObservation, ...]:
        request = AttachmentMetadataRequest(start=0, limit=self._page_size)
        seen: set[AttachmentMetadataRequest] = set()
        output: list[ConfluenceAttachmentObservation] = []
        while True:
            if request in seen or len(seen) >= self._max_pages:
                raise ValueError("attachment pagination failed")
            seen.add(request)
            parsed = parse_attachment_metadata_window(
                raw_bytes=self._adapter.fetch_attachment_metadata(page_id=page_id, request=request),
                selected_page_id=page_id, request=request,
            )
            for item in parsed.attachments:
                version_number = item.get("version_number")
                output.append(ConfluenceAttachmentObservation(
                    attachment_id=item["attachment_id"], parent_page_id=item["source_page_id"],
                    filename=item["filename"], mime_type=item.get("mime_type"),
                    size_bytes=item.get("file_size"),
                    source_version=str(version_number) if version_number is not None else None,
                    crawled_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                ))
            if parsed.next_request is None:
                return tuple(output)
            request = parsed.next_request


__all__ = ["LiveSubtreeComposition", "compose_live_subtree"]
