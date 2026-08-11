"""Evidence-bound second-sync inventory models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from knowledgenexus.foundation.domain.models.delta_propagation import (
    DeltaInventoryEntry,
    DeltaInventoryState,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator

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
        page = _text(self.page_id, "page_id")
        document = _text(self.document_id, "document_id")
        if document != DocumentIdGenerator.confluence_page_id(page):
            raise ValueError("document identity is invalid")
        _text(self.source_version_last_seen, "source_version_last_seen")


@dataclass(frozen=True, repr=False)
class CurrentSelectionPage:
    page_id: str

    def __post_init__(self) -> None:
        _fields(self, {"page_id"})
        _text(self.page_id, "page_id")


@dataclass(frozen=True, repr=False)
class DeltaInventoryScope:
    include_root_page_ids: tuple[str, ...]
    excluded_page_ids: tuple[str, ...] = ()
    excluded_ancestor_page_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _fields(self, {"include_root_page_ids", "excluded_page_ids", "excluded_ancestor_page_ids"})
        for name in ("include_root_page_ids", "excluded_page_ids", "excluded_ancestor_page_ids"):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(item) is not str or not item for item in values):
                raise ValueError("scope is invalid")
            if len(set(values)) != len(values):
                raise ValueError("scope is invalid")


@dataclass(frozen=True, repr=False)
class DeltaInventoryObservation:
    page_id: str
    http_status: int
    ancestor_page_ids: tuple[str, ...]
    response_byte_count: int
    response_sha256: str
    source_version_last_seen: str
    under_include_root: bool = False
    excluded_by_id: bool = False
    excluded_by_ancestor: bool = False

    def __post_init__(self) -> None:
        _fields(self, {"page_id", "http_status", "ancestor_page_ids", "response_byte_count", "response_sha256", "source_version_last_seen", "under_include_root", "excluded_by_id", "excluded_by_ancestor"})
        _text(self.page_id, "page_id")
        if type(self.http_status) is not int or isinstance(self.http_status, bool) or not 100 <= self.http_status <= 599:
            raise ValueError("observation is invalid")
        if type(self.ancestor_page_ids) is not tuple or any(type(item) is not str or not item for item in self.ancestor_page_ids):
            raise ValueError("observation is invalid")
        if type(self.response_byte_count) is not int or isinstance(self.response_byte_count, bool) or self.response_byte_count < 0:
            raise ValueError("observation is invalid")
        if type(self.response_sha256) is not str or _SHA256.fullmatch(self.response_sha256) is None:
            raise ValueError("observation is invalid")
        _text(self.source_version_last_seen, "source_version_last_seen")
        if type(self.under_include_root) is not bool or type(self.excluded_by_id) is not bool or type(self.excluded_by_ancestor) is not bool:
            raise ValueError("observation is invalid")


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


@dataclass(frozen=True, repr=False)
class DeltaInventoryClassificationRequest:
    prior_documents: tuple[PriorConfluenceDocument, ...]
    current_selection: tuple[CurrentSelectionPage, ...]
    scope: DeltaInventoryScope
    observations: tuple[DeltaInventoryObservation, ...] = ()

    def __post_init__(self) -> None:
        _fields(self, {"prior_documents", "current_selection", "scope", "observations"})
        if type(self.prior_documents) is not tuple or any(type(item) is not PriorConfluenceDocument for item in self.prior_documents):
            raise ValueError("prior snapshot is invalid")
        if type(self.current_selection) is not tuple or any(type(item) is not CurrentSelectionPage for item in self.current_selection):
            raise ValueError("selection is invalid")
        if type(self.scope) is not DeltaInventoryScope:
            raise ValueError("scope is invalid")
        if type(self.observations) is not tuple or any(type(item) is not DeltaInventoryObservation for item in self.observations):
            raise ValueError("observations are invalid")
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
        if self.error_category is not None or type(self.metrics) is not DeltaInventoryMetrics or any(type(entry) is not DeltaInventoryEntry for entry in self.entries):
            raise ValueError("result is invalid")
        if tuple(sorted(self.entries, key=lambda entry: entry.document_id)) != self.entries or len({entry.document_id for entry in self.entries}) != len(self.entries):
            raise ValueError("result is invalid")


__all__ = [
    "CurrentSelectionPage", "DeltaInventoryClassificationRequest", "DeltaInventoryClassificationResult",
    "DeltaInventoryFailureCategory", "DeltaInventoryMetrics", "DeltaInventoryObservation", "DeltaInventoryScope",
    "DeltaInventoryStatus", "PriorConfluenceDocument", "DeltaInventoryState", "DeltaInventoryEntry", "_DETAIL_404",
]
