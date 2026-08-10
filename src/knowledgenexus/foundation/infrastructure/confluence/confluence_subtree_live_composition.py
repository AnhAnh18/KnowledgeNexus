"""Production composition root for the bounded Root 1 subtree crawler.

This module only wires approved infrastructure seams.  It deliberately does
not implement HTTP, pagination, retry, checkpoint, or raw-store behavior.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_inventory_adapter import (
    ConfluenceDataCenterInventoryAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_adapter import (
    ConfluenceDataCenterPageAdapter,
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

    def __repr__(self) -> str:
        return "LiveSubtreeComposition()"

    def inventory_use_case(self, *, max_search_pages: int) -> ExecuteDurableConfluenceInventory:
        """Bind the durable inventory loop to this production adapter factory."""
        if type(max_search_pages) is not int or max_search_pages <= 0:
            raise ValueError("max_search_pages must be positive")
        return ExecuteDurableConfluenceInventory(
            checkpoint_run_port=self.checkpoint_run_port,
            inventory_transport_factory=lambda _activation: self.transport,
            inventory_window_port_factory=lambda transport: ConfluenceDataCenterInventoryAdapter(
                transport=transport, max_search_pages=max_search_pages
            ),
        )


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
    )


__all__ = ["LiveSubtreeComposition", "compose_live_subtree"]
