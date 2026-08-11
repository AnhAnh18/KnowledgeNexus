"""Durable, status-aware W4-C1 disposition capture."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from knowledgenexus.foundation.application.use_cases.classify_delta_inventory import ClassifyDeltaInventory
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import ConfluenceRawPageEnvelope
from knowledgenexus.foundation.domain.models.delta_inventory import (
    CurrentSelectionPage,
    DeltaInventoryClassificationRequest,
    DeltaInventoryEnvelope,
    DeltaInventoryFailureCategory,
    DeltaInventoryObservation,
    DeltaInventoryScope,
    PriorConfluenceDocument,
)


_PAGE_PATH = "/rest/api/content/{page_id}"
_PAGE_QUERY = {"expand": "ancestors"}
_SHA256 = "0123456789abcdef"


class DeltaInventoryCaptureFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    PROBE_FAILED = "probe_failed"
    RAW_EVIDENCE_FAILED = "raw_evidence_failed"
    CLASSIFICATION_FAILED = "classification_failed"
    ARTIFACT_FAILED = "artifact_failed"


class DeltaInventoryCaptureError(Exception):
    def __init__(self, category: DeltaInventoryCaptureFailureCategory) -> None:
        if not isinstance(category, DeltaInventoryCaptureFailureCategory):
            raise TypeError("invalid category")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"DeltaInventoryCaptureError('{self.category.value}')"


class _Response(Protocol):
    status_code: int
    body: bytes


@dataclass(frozen=True, repr=False)
class DeltaInventoryCaptureRequest:
    run_id: CrawlRunId
    generation_id: CrawlRunId
    accepted_base_dataset_version: str
    current_selection_identity: str
    current_scope_identity: str
    prior_documents: tuple[PriorConfluenceDocument, ...]
    current_selection: tuple[CurrentSelectionPage, ...]
    scope: DeltaInventoryScope
    transport: object
    raw_page_store: object
    artifact_store: object

    def __post_init__(self) -> None:
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId or self.run_id != self.generation_id:
            raise ValueError("invalid capture identity")
        CrawlRunId(self.run_id.value)
        if type(self.accepted_base_dataset_version) is not str or not self.accepted_base_dataset_version or any(ch.isspace() for ch in self.accepted_base_dataset_version):
            raise ValueError("invalid base dataset version")
        for value in (self.current_selection_identity, self.current_scope_identity):
            if type(value) is not str or len(value) != 64 or any(ch not in _SHA256 for ch in value):
                raise ValueError("invalid identity")
        if type(self.prior_documents) is not tuple or type(self.current_selection) is not tuple or type(self.scope) is not DeltaInventoryScope:
            raise ValueError("invalid capture input")
        for item in self.prior_documents:
            if type(item) is not PriorConfluenceDocument:
                raise ValueError("invalid prior snapshot")
            PriorConfluenceDocument.__post_init__(item)
        for item in self.current_selection:
            if type(item) is not CurrentSelectionPage:
                raise ValueError("invalid selection")
            CurrentSelectionPage.__post_init__(item)
        DeltaInventoryScope.__post_init__(self.scope)
        if len({item.page_id for item in self.prior_documents}) != len(self.prior_documents) or len({item.page_id for item in self.current_selection}) != len(self.current_selection):
            raise ValueError("duplicate page IDs")
        if not callable(getattr(self.transport, "get_response_bytes", None)):
            raise ValueError("invalid transport")
        if not callable(getattr(self.raw_page_store, "publish_page", None)) or not callable(getattr(self.raw_page_store, "read_page", None)):
            raise ValueError("invalid raw store")
        if not callable(getattr(self.artifact_store, "publish", None)):
            raise ValueError("invalid artifact store")


def selection_identity(selection: tuple[CurrentSelectionPage, ...]) -> str:
    return _digest([item.page_id for item in selection])


def scope_identity(scope: DeltaInventoryScope) -> str:
    return _digest({
        "include_root_page_ids": list(scope.include_root_page_ids),
        "excluded_page_ids": list(scope.excluded_page_ids),
        "excluded_ancestor_page_ids": list(scope.excluded_ancestor_page_ids),
    })


class CaptureDeltaInventory:
    def execute(self, request: object) -> DeltaInventoryEnvelope:
        try:
            if type(request) is not DeltaInventoryCaptureRequest:
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.INVALID_INPUT)
            if selection_identity(request.current_selection) != request.current_selection_identity or scope_identity(request.scope) != request.current_scope_identity:
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.INVALID_INPUT)
            missing = sorted({item.page_id for item in request.prior_documents} - {item.page_id for item in request.current_selection})
            observations: list[DeltaInventoryObservation] = []
            prior_by_page = {item.page_id: item for item in request.prior_documents}
            for page_id in missing:
                prior = prior_by_page[page_id]
                envelope = self._read_or_probe(request, page_id, prior.source_version_last_seen)
                observations.append(self._observation(envelope))
            classified = ClassifyDeltaInventory().execute(
                DeltaInventoryClassificationRequest(
                    request.prior_documents,
                    request.current_selection,
                    request.scope,
                    tuple(observations),
                )
            )
            if classified.status.value != "success":
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.CLASSIFICATION_FAILED)
            envelope = DeltaInventoryEnvelope(
                "1.0.0", request.run_id, request.generation_id,
                request.current_selection_identity,
                request.accepted_base_dataset_version,
                request.current_scope_identity,
                classified.entries,
                classified.metrics,
            )
            try:
                request.artifact_store.publish(envelope=envelope)
            except Exception:
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.ARTIFACT_FAILED) from None
            return envelope
        except DeltaInventoryCaptureError:
            raise
        except Exception:
            raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.INVALID_INPUT) from None

    @staticmethod
    def _read_or_probe(request: DeltaInventoryCaptureRequest, page_id: str, source_version: str) -> ConfluenceRawPageEnvelope:
        try:
            existing = request.raw_page_store.read_page(run_id=request.run_id, page_id=page_id)
            if type(existing) is not ConfluenceRawPageEnvelope or existing.source_version != source_version:
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.RAW_EVIDENCE_FAILED)
            return existing
        except DeltaInventoryCaptureError:
            raise
        except Exception:
            pass
        try:
            response = request.transport.get_response_bytes(path=_PAGE_PATH.format(page_id=urllib.parse.quote(page_id, safe="")), query=dict(_PAGE_QUERY))
            status = getattr(response, "status_code", None)
            body = getattr(response, "body", None)
            envelope = ConfluenceRawPageEnvelope.capture(run_id=request.run_id, page_id=page_id, source_version=source_version, http_status=status, body_bytes=body)
            request.raw_page_store.publish_page(envelope=envelope)
            return envelope
        except DeltaInventoryCaptureError:
            raise
        except Exception:
            raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.PROBE_FAILED) from None

    @staticmethod
    def _observation(envelope: ConfluenceRawPageEnvelope) -> DeltaInventoryObservation:
        ancestors: tuple[str, ...] = ()
        if envelope.http_status == 200:
            try:
                payload = json.loads(envelope.body_bytes.decode("utf-8"))
                values = payload.get("ancestors") if type(payload) is dict else None
                if type(values) is not list:
                    raise ValueError
                ancestors = tuple(str(item["id"]) for item in values if type(item) is dict and type(item.get("id")) is str)
            except Exception:
                raise DeltaInventoryCaptureError(DeltaInventoryCaptureFailureCategory.PROBE_FAILED) from None
        return DeltaInventoryObservation(
            envelope.page_id,
            envelope.http_status,
            ancestors,
            len(envelope.body_bytes),
            hashlib.sha256(envelope.body_bytes).hexdigest(),
            envelope.source_version or "unknown",
        )


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


__all__ = ["CaptureDeltaInventory", "DeltaInventoryCaptureError", "DeltaInventoryCaptureFailureCategory", "DeltaInventoryCaptureRequest", "scope_identity", "selection_identity"]
