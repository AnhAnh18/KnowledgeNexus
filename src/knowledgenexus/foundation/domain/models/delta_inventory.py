"""Evidence-bound second-sync inventory models."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from knowledgenexus.foundation.domain.models.delta_propagation import (
    DeltaInventoryEntry,
    DeltaInventoryState,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.domain.rules.confluence_page_id import require_confluence_page_id
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE = re.compile(r"^\S+$")
_DETAIL_404 = "confluence_404_may_mask_access_revoked"


def _fields(value: object, expected: set[str]) -> None:
    try:
        if set(vars(value)) != expected:
            raise TypeError("model fields are invalid")
    except TypeError:
        raise TypeError("model fields are invalid") from None


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or _OPAQUE.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


def _identity(value: object, name: str) -> str:
    if type(value) is not str or not value or _OPAQUE.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


class DeltaInventoryFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_PRIOR_SNAPSHOT = "invalid_prior_snapshot"
    INVALID_SELECTION_SCOPE = "invalid_selection_scope"
    INVALID_OBSERVATION = "invalid_observation"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    INVENTORY_INCONSISTENT = "inventory_inconsistent"
    INVALID_RESULT = "invalid_result"
    INTERNAL_FAILURE = "internal_failure"


class DeltaInventoryStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, repr=False)
class PriorConfluenceDocument:
    page_id: str
    document_id: str
    source_version_last_seen: str

    def __post_init__(self) -> None:
        _fields(self, {"page_id", "document_id", "source_version_last_seen"})
        page = require_confluence_page_id(self.page_id)
        document = _text(self.document_id, "document_id")
        if document != DocumentIdGenerator.confluence_page_id(page):
            raise ValueError("document identity is invalid")
        _text(self.source_version_last_seen, "source_version_last_seen")


@dataclass(frozen=True, repr=False)
class CurrentSelectionPage:
    page_id: str

    def __post_init__(self) -> None:
        _fields(self, {"page_id"})
        require_confluence_page_id(self.page_id)


@dataclass(frozen=True, repr=False)
class DeltaInventoryScope:
    include_root_page_ids: tuple[str, ...]
    excluded_page_ids: tuple[str, ...] = ()
    excluded_ancestor_page_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _fields(self, {"include_root_page_ids", "excluded_page_ids", "excluded_ancestor_page_ids"})
        for name in ("include_root_page_ids", "excluded_page_ids", "excluded_ancestor_page_ids"):
            values = getattr(self, name)
            if type(values) is not tuple:
                raise ValueError("scope is invalid")
            for item in values:
                require_confluence_page_id(item)
            if len(set(values)) != len(values):
                raise ValueError("scope is invalid")
        if not self.include_root_page_ids:
            raise ValueError("scope is invalid")


@dataclass(frozen=True, repr=False)
class DeltaInventoryObservation:
    page_id: str
    http_status: int
    ancestor_page_ids: tuple[str, ...]
    response_byte_count: int
    response_sha256: str
    source_version_last_seen: str

    def __post_init__(self) -> None:
        _fields(self, {"page_id", "http_status", "ancestor_page_ids", "response_byte_count", "response_sha256", "source_version_last_seen"})
        require_confluence_page_id(self.page_id)
        if type(self.http_status) is not int or isinstance(self.http_status, bool) or not 100 <= self.http_status <= 599:
            raise ValueError("observation is invalid")
        if type(self.ancestor_page_ids) is not tuple:
            raise ValueError("observation is invalid")
        for item in self.ancestor_page_ids:
            require_confluence_page_id(item)
        if len(set(self.ancestor_page_ids)) != len(self.ancestor_page_ids):
            raise ValueError("observation is invalid")
        if type(self.response_byte_count) is not int or isinstance(self.response_byte_count, bool) or self.response_byte_count < 0:
            raise ValueError("observation is invalid")
        if type(self.response_sha256) is not str or _SHA256.fullmatch(self.response_sha256) is None:
            raise ValueError("observation is invalid")
        _text(self.source_version_last_seen, "source_version_last_seen")


@dataclass(frozen=True, repr=False)
class DeltaInventoryMetrics:
    present_count: int
    source_deleted_count: int
    access_revoked_count: int
    moved_out_of_scope_count: int

    def __post_init__(self) -> None:
        _fields(self, {"present_count", "source_deleted_count", "access_revoked_count", "moved_out_of_scope_count"})
        values = tuple(getattr(self, name) for name in vars(self))
        if any(type(value) is not int or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("metrics are invalid")

    @property
    def total_count(self) -> int:
        return self.present_count + self.source_deleted_count + self.access_revoked_count + self.moved_out_of_scope_count


@dataclass(frozen=True, repr=False)
class DeltaInventoryClassificationRequest:
    prior_documents: tuple[PriorConfluenceDocument, ...]
    current_selection: tuple[CurrentSelectionPage, ...]
    scope: DeltaInventoryScope
    observations: tuple[DeltaInventoryObservation, ...] = ()

    def __post_init__(self) -> None:
        _fields(self, {"prior_documents", "current_selection", "scope", "observations"})
        if type(self.prior_documents) is not tuple:
            raise ValueError("prior snapshot is invalid")
        for item in self.prior_documents:
            if type(item) is not PriorConfluenceDocument:
                raise ValueError("prior snapshot is invalid")
            PriorConfluenceDocument.__post_init__(item)
        if type(self.current_selection) is not tuple:
            raise ValueError("selection is invalid")
        for item in self.current_selection:
            if type(item) is not CurrentSelectionPage:
                raise ValueError("selection is invalid")
            CurrentSelectionPage.__post_init__(item)
        if type(self.scope) is not DeltaInventoryScope:
            raise ValueError("scope is invalid")
        DeltaInventoryScope.__post_init__(self.scope)
        if type(self.observations) is not tuple:
            raise ValueError("observations are invalid")
        for item in self.observations:
            if type(item) is not DeltaInventoryObservation:
                raise ValueError("observations are invalid")
            DeltaInventoryObservation.__post_init__(item)
        if len({item.page_id for item in self.prior_documents}) != len(self.prior_documents) or len({item.page_id for item in self.current_selection}) != len(self.current_selection) or len({item.page_id for item in self.observations}) != len(self.observations):
            raise ValueError("duplicate IDs are invalid")


@dataclass(frozen=True, repr=False)
class DeltaInventoryClassificationResult:
    status: DeltaInventoryStatus
    entries: tuple[DeltaInventoryEntry, ...] = ()
    metrics: DeltaInventoryMetrics | None = None
    error_category: DeltaInventoryFailureCategory | None = None

    def __post_init__(self) -> None:
        _fields(self, {"status", "entries", "metrics", "error_category"})
        if type(self.status) is not DeltaInventoryStatus or type(self.entries) is not tuple:
            raise ValueError("result is invalid")
        if self.status is DeltaInventoryStatus.FAILED:
            if self.entries or self.metrics is not None or type(self.error_category) is not DeltaInventoryFailureCategory:
                raise ValueError("result is invalid")
            return
        if self.error_category is not None or type(self.metrics) is not DeltaInventoryMetrics:
            raise ValueError("result is invalid")
        DeltaInventoryMetrics.__post_init__(self.metrics)
        for entry in self.entries:
            _validate_w4_entry(entry)
        counts = {
            DeltaInventoryState.PRESENT: self.metrics.present_count,
            DeltaInventoryState.SOURCE_DELETED: self.metrics.source_deleted_count,
            DeltaInventoryState.ACCESS_REVOKED: self.metrics.access_revoked_count,
            DeltaInventoryState.MOVED_OUT_OF_SCOPE: self.metrics.moved_out_of_scope_count,
        }
        if any(sum(entry.state is state for entry in self.entries) != count for state, count in counts.items()):
            raise ValueError("result is invalid")
        if self.metrics.total_count != len(self.entries):
            raise ValueError("result is invalid")
        if tuple(sorted(self.entries, key=lambda entry: entry.document_id)) != self.entries or len({entry.document_id for entry in self.entries}) != len(self.entries):
            raise ValueError("result is invalid")


DELTA_INVENTORY_FORMAT_VERSION = "1.0.0"


@dataclass(frozen=True, repr=False)
class DeltaInventoryEnvelope:
    format_version: str
    run_id: CrawlRunId
    generation_id: CrawlRunId
    current_selection_identity: str
    accepted_base_dataset_version: str
    current_scope_identity: str
    entries: tuple[DeltaInventoryEntry, ...]
    metrics: DeltaInventoryMetrics

    def __post_init__(self) -> None:
        _fields(self, {"format_version", "run_id", "generation_id", "current_selection_identity", "accepted_base_dataset_version", "current_scope_identity", "entries", "metrics"})
        if self.format_version != DELTA_INVENTORY_FORMAT_VERSION:
            raise ValueError("envelope is invalid")
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId:
            raise ValueError("envelope is invalid")
        CrawlRunId(self.run_id.value)
        CrawlRunId(self.generation_id.value)
        if self.run_id != self.generation_id:
            raise ValueError("envelope is invalid")
        for name in ("current_selection_identity", "current_scope_identity"):
            value = getattr(self, name)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise ValueError("envelope is invalid")
        _identity(self.accepted_base_dataset_version, "accepted_base_dataset_version")
        if type(self.entries) is not tuple or type(self.metrics) is not DeltaInventoryMetrics:
            raise ValueError("envelope is invalid")
        DeltaInventoryMetrics.__post_init__(self.metrics)
        for entry in self.entries:
            _validate_w4_entry(entry)
        if tuple(sorted(self.entries, key=lambda item: item.document_id)) != self.entries or len({item.document_id for item in self.entries}) != len(self.entries):
            raise ValueError("envelope is invalid")
        counts = {
            DeltaInventoryState.PRESENT: self.metrics.present_count,
            DeltaInventoryState.SOURCE_DELETED: self.metrics.source_deleted_count,
            DeltaInventoryState.ACCESS_REVOKED: self.metrics.access_revoked_count,
            DeltaInventoryState.MOVED_OUT_OF_SCOPE: self.metrics.moved_out_of_scope_count,
        }
        if any(sum(entry.state is state for entry in self.entries) != count for state, count in counts.items()):
            raise ValueError("envelope is invalid")
        if self.metrics.total_count != len(self.entries):
            raise ValueError("envelope is invalid")

    def to_bytes(self) -> bytes:
        payload = {
            "format_version": self.format_version,
            "run_id": str(self.run_id),
            "generation_id": str(self.generation_id),
            "current_selection_identity": self.current_selection_identity,
            "accepted_base_dataset_version": self.accepted_base_dataset_version,
            "current_scope_identity": self.current_scope_identity,
            "entries": [
                {
                    "document_id": entry.document_id,
                    "state": entry.state.value,
                    "source_version_last_seen": entry.source_version_last_seen,
                    "detail": entry.detail,
                }
                for entry in self.entries
            ],
            "metrics": {
                "present_count": self.metrics.present_count,
                "source_deleted_count": self.metrics.source_deleted_count,
                "access_revoked_count": self.metrics.access_revoked_count,
                "moved_out_of_scope_count": self.metrics.moved_out_of_scope_count,
            },
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, serialized: bytes) -> "DeltaInventoryEnvelope":
        if type(serialized) is not bytes:
            raise ValueError("envelope is invalid")
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("envelope is invalid")
                result[key] = value
            return result
        try:
            payload = json.loads(serialized.decode("utf-8"), object_pairs_hook=reject_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if type(payload) is not dict:
                raise ValueError
            entries_payload = payload["entries"]
            metrics_payload = payload["metrics"]
            if type(entries_payload) is not list or type(metrics_payload) is not dict:
                raise ValueError
            entries = tuple(
                DeltaInventoryEntry(
                    item["document_id"],
                    DeltaInventoryState(item["state"]),
                    item["source_version_last_seen"],
                    item["detail"],
                )
                for item in entries_payload
            )
            envelope = cls(
                payload["format_version"],
                CrawlRunId(payload["run_id"]),
                CrawlRunId(payload["generation_id"]),
                payload["current_selection_identity"],
                payload["accepted_base_dataset_version"],
                payload["current_scope_identity"],
                entries,
                DeltaInventoryMetrics(
                    metrics_payload["present_count"],
                    metrics_payload["source_deleted_count"],
                    metrics_payload["access_revoked_count"],
                    metrics_payload["moved_out_of_scope_count"],
                ),
            )
        except Exception:
            raise ValueError("envelope is invalid") from None
        if envelope.to_bytes() != serialized:
            raise ValueError("envelope is invalid")
        return envelope


def _validate_w4_entry(entry: object) -> DeltaInventoryEntry:
    if type(entry) is not DeltaInventoryEntry:
        raise ValueError("result is invalid")
    DeltaInventoryEntry.__post_init__(entry)
    prefix = "confluence:page:"
    if not entry.document_id.startswith(prefix):
        raise ValueError("result is invalid")
    page_id = entry.document_id[len(prefix):]
    require_confluence_page_id(page_id)
    if DocumentIdGenerator.confluence_page_id(page_id) != entry.document_id:
        raise ValueError("result is invalid")
    if entry.state is DeltaInventoryState.PRESENT:
        if entry.source_version_last_seen is not None or entry.detail is not None:
            raise ValueError("result is invalid")
    elif entry.state is DeltaInventoryState.SOURCE_DELETED:
        if not entry.source_version_last_seen or entry.detail != _DETAIL_404:
            raise ValueError("result is invalid")
    elif entry.state in (DeltaInventoryState.ACCESS_REVOKED, DeltaInventoryState.MOVED_OUT_OF_SCOPE):
        if not entry.source_version_last_seen or entry.detail is not None:
            raise ValueError("result is invalid")
    else:
        raise ValueError("result is invalid")
    return entry


__all__ = [
    "CurrentSelectionPage", "DeltaInventoryClassificationRequest", "DeltaInventoryClassificationResult", "DeltaInventoryEnvelope",
    "DeltaInventoryFailureCategory", "DeltaInventoryMetrics", "DeltaInventoryObservation", "DeltaInventoryScope",
    "DeltaInventoryStatus", "PriorConfluenceDocument", "DELTA_INVENTORY_FORMAT_VERSION", "DeltaInventoryState", "DeltaInventoryEntry", "_DETAIL_404",
]
