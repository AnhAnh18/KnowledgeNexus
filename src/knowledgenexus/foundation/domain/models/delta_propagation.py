"""Runtime-validated models for read-only delta propagation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from knowledgenexus.foundation.domain.models.chunk_stability import (
    ChunkStabilityEntry,
    DocumentChunkSetSummary,
)
from knowledgenexus.foundation.domain.models.tombstone_propagation import (
    TombstoneEntityType,
    TombstoneTarget,
    TombstoneProjectionMetrics,
    TombstoneProjectionResult,
    TombstoneProjectionStatus,
)


_OPAQUE = re.compile(r"^\S+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENT_ID = re.compile(r"^confluence:page:\S+$")
_MISSING = object()
_ENTITY_RANK = {"document": 0, "chunk": 1, "media": 2, "relation": 3, "acl": 4, "symbol": 5}
_OUTCOME_STATES = frozenset({"new", "unchanged", "changed", "removed"})


class _SummaryValidationError(ValueError):
    pass


class _InventoryConflictError(ValueError):
    pass


def _require_exact_fields(instance: object, expected: frozenset[str]) -> None:
    try:
        actual = frozenset(vars(instance))
    except TypeError:
        raise TypeError("model fields are invalid") from None
    if actual != expected:
        raise TypeError("model fields are invalid")


def _opaque(name: str, value: object) -> str:
    if type(value) is not str or not value or _OPAQUE.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or not re.fullmatch(
        r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$",
        value,
    ):
        raise ValueError("detected_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("detected_at is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("detected_at is invalid")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_summary(summary: object) -> DocumentChunkSetSummary:
    if type(summary) is not DocumentChunkSetSummary:
        raise _SummaryValidationError("summary is invalid")
    try:
        _require_exact_fields(
            summary,
            frozenset({
                "format_version", "document_id", "document_content_hash", "chunker_version",
                "profile_identity", "entries", "chunk_count", "content_kind_counts",
            }),
        )
        if type(summary.entries) is not tuple:
            raise TypeError("summary entries are invalid")
        for entry in summary.entries:
            if type(entry) is not ChunkStabilityEntry:
                raise TypeError("summary entry is invalid")
            _require_exact_fields(
                entry,
                frozenset({"chunk_id", "content_hash", "content_kind", "token_count", "part_index", "part_total"}),
            )
            ChunkStabilityEntry.__post_init__(entry)
        DocumentChunkSetSummary.__post_init__(summary)
    except Exception:
        raise _SummaryValidationError("summary is invalid") from None
    return summary


class DeltaInventoryState(StrEnum):
    PRESENT = "present"
    SOURCE_DELETED = "source_deleted"
    ACCESS_REVOKED = "access_revoked"
    MOVED_OUT_OF_SCOPE = "moved_out_of_scope"
    CONFIG_INVALIDATED = "config_invalidated"


@dataclass(frozen=True, repr=False)
class DeltaInventoryEntry:
    document_id: str
    state: DeltaInventoryState
    source_version_last_seen: str | None = None

    def __post_init__(self) -> None:
        _require_exact_fields(self, frozenset({"document_id", "state", "source_version_last_seen"}))
        if type(self.document_id) is not str or _DOCUMENT_ID.fullmatch(self.document_id) is None:
            raise ValueError("document_id is invalid")
        if type(self.state) is not DeltaInventoryState:
            raise TypeError("state is invalid")
        if self.source_version_last_seen is not None:
            _opaque("source_version_last_seen", self.source_version_last_seen)


@dataclass(frozen=True, repr=False)
class DeltaPropagationRequest:
    previous_dataset_version: str
    current_dataset_version: str
    previous_config_hash: str
    current_config_hash: str
    detected_at: str
    previous_summaries: tuple[DocumentChunkSetSummary, ...]
    current_summaries: tuple[DocumentChunkSetSummary, ...]
    inventory: tuple[DeltaInventoryEntry, ...] = ()
    previous_dependents: tuple[tuple[str, tuple[TombstoneTarget, ...]], ...] = ()
    previous_acl_hashes: tuple[tuple[str, str], ...] = ()
    current_acl_hashes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        expected_fields = frozenset({
            "previous_dataset_version", "current_dataset_version", "previous_config_hash",
            "current_config_hash", "detected_at", "previous_summaries", "current_summaries", "inventory", "previous_dependents", "previous_acl_hashes", "current_acl_hashes",
        })
        actual_fields = frozenset(vars(self))
        # previous_dependents was introduced as an optional wire extension;
        # accept legacy in-memory requests and normalize the absent field.
        missing_optional = expected_fields - actual_fields
        if (actual_fields - expected_fields) or not missing_optional.issubset({"previous_dependents", "previous_acl_hashes", "current_acl_hashes"}):
            raise TypeError("model fields are invalid")
        if missing_optional:
            for field in missing_optional:
                object.__setattr__(self, field, ())
        previous = _opaque("previous_dataset_version", self.previous_dataset_version)
        current = _opaque("current_dataset_version", self.current_dataset_version)
        if previous == current:
            raise ValueError("dataset versions must differ")
        for name, value in (("previous_config_hash", self.previous_config_hash), ("current_config_hash", self.current_config_hash)):
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} is invalid")
        object.__setattr__(self, "previous_dataset_version", previous)
        object.__setattr__(self, "current_dataset_version", current)
        object.__setattr__(self, "detected_at", _timestamp(self.detected_at))
        for name in ("previous_summaries", "current_summaries"):
            summaries = getattr(self, name, _MISSING)
            if type(summaries) is not tuple:
                raise _SummaryValidationError(f"{name} is invalid")
            seen: set[str] = set()
            for summary in summaries:
                summary = _validate_summary(summary)
                if summary.document_id in seen:
                    raise _SummaryValidationError(f"{name} contain duplicate IDs")
                seen.add(summary.document_id)
        if type(self.inventory) is not tuple:
            raise TypeError("inventory is invalid")
        seen_inventory: set[str] = set()
        for entry in self.inventory:
            if type(entry) is not DeltaInventoryEntry:
                raise TypeError("inventory entries are invalid")
            try:
                DeltaInventoryEntry.__post_init__(entry)
            except Exception:
                raise TypeError("inventory entries are invalid") from None
            if entry.document_id in seen_inventory:
                raise _InventoryConflictError("inventory contains duplicate IDs")
            seen_inventory.add(entry.document_id)
        if type(self.previous_dependents) is not tuple:
            raise TypeError("previous_dependents is invalid")
        seen_dependents: set[str] = set()
        for item in self.previous_dependents:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("previous_dependents entries are invalid")
            document_id, targets = item
            if type(document_id) is not str or _DOCUMENT_ID.fullmatch(document_id) is None or document_id in seen_dependents:
                raise ValueError("previous dependent document ID is invalid")
            seen_dependents.add(document_id)
            if type(targets) is not tuple or any(type(target) is not TombstoneTarget for target in targets):
                raise TypeError("previous dependent targets are invalid")
            target_keys: set[tuple[TombstoneEntityType, str]] = set()
            for target in targets:
                TombstoneTarget.__post_init__(target)
                if target.entity_type is TombstoneEntityType.DOCUMENT:
                    raise ValueError("document cannot be a dependent target")
                key = (target.entity_type, target.entity_id)
                if key in target_keys:
                    raise ValueError("previous dependent targets contain duplicate IDs")
                target_keys.add(key)
        object.__setattr__(self, "previous_dependents", tuple(self.previous_dependents))
        for field in ("previous_acl_hashes", "current_acl_hashes"):
            values = getattr(self, field)
            if type(values) is not tuple:
                raise TypeError(f"{field} is invalid")
            seen_acl: set[str] = set()
            for item in values:
                if type(item) is not tuple or len(item) != 2:
                    raise TypeError(f"{field} entries are invalid")
                document_id, fingerprint = item
                if type(document_id) is not str or _DOCUMENT_ID.fullmatch(document_id) is None or document_id in seen_acl:
                    raise ValueError(f"{field} document ID is invalid")
                if type(fingerprint) is not str or _SHA256.fullmatch(fingerprint) is None:
                    raise ValueError(f"{field} fingerprint is invalid")
                seen_acl.add(document_id)
            object.__setattr__(self, field, tuple(values))


@dataclass(frozen=True, repr=False)
class DeltaPropagationMetrics:
    document_count: int
    new_document_count: int
    unchanged_document_count: int
    changed_document_count: int
    removed_document_count: int
    document_tombstone_count: int
    chunk_tombstone_count: int
    record_count: int
    media_tombstone_count: int = 0
    relation_tombstone_count: int = 0
    acl_tombstone_count: int = 0
    symbol_tombstone_count: int = 0

    def __post_init__(self) -> None:
        _require_exact_fields(
            self,
            frozenset({
                "document_count", "new_document_count", "unchanged_document_count", "changed_document_count",
                "removed_document_count", "document_tombstone_count", "chunk_tombstone_count", "record_count",
                "media_tombstone_count", "relation_tombstone_count", "acl_tombstone_count", "symbol_tombstone_count",
            }),
        )
        values = (
            self.document_count, self.new_document_count, self.unchanged_document_count,
            self.changed_document_count, self.removed_document_count, self.document_tombstone_count,
            self.chunk_tombstone_count, self.record_count, self.media_tombstone_count,
            self.relation_tombstone_count, self.acl_tombstone_count, self.symbol_tombstone_count,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("metrics are invalid")
        if self.document_count != self.new_document_count + self.unchanged_document_count + self.changed_document_count + self.removed_document_count:
            raise ValueError("document metrics are inconsistent")
        if self.document_tombstone_count > self.document_count:
            raise ValueError("document metrics are inconsistent")
        if self.record_count != self.document_tombstone_count + self.chunk_tombstone_count + self.media_tombstone_count + self.relation_tombstone_count + self.acl_tombstone_count + self.symbol_tombstone_count:
            raise ValueError("record metrics are inconsistent")


class DeltaPropagationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class DeltaPropagationFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_DEPENDENCY = "invalid_dependency"
    SUMMARY_INVALID = "summary_invalid"
    INVENTORY_CONFLICT = "inventory_conflict"
    TOMBSTONE_FAILURE = "tombstone_failure"
    RESULT_INVALID = "result_invalid"
    INTERNAL_FAILURE = "internal_failure"


def _record_key(record: dict[str, object]) -> tuple[int, str, str]:
    entity_type = record.get("entity_type")
    entity_id = record.get("entity_id")
    tombstone_id = record.get("tombstone_id")
    if type(entity_type) is not str or type(entity_id) is not str or type(tombstone_id) is not str:
        raise ValueError("record identity is invalid")
    return (_ENTITY_RANK.get(entity_type, 99), entity_id, tombstone_id)


def _canonical_payload(result: "DeltaPropagationResult") -> dict[str, object]:
    metrics = result.metrics
    return {
        "base_dataset_version": result.base_dataset_version,
        "count": result.count,
        "dataset_version": result.dataset_version,
        "metrics": {
            "changed_document_count": metrics.changed_document_count,
            "chunk_tombstone_count": metrics.chunk_tombstone_count,
            "document_count": metrics.document_count,
            "document_tombstone_count": metrics.document_tombstone_count,
            "new_document_count": metrics.new_document_count,
            "record_count": metrics.record_count,
            "removed_document_count": metrics.removed_document_count,
            "unchanged_document_count": metrics.unchanged_document_count,
            "media_tombstone_count": metrics.media_tombstone_count,
            "relation_tombstone_count": metrics.relation_tombstone_count,
            "acl_tombstone_count": metrics.acl_tombstone_count,
            "symbol_tombstone_count": metrics.symbol_tombstone_count,
        } if metrics is not None else None,
        "document_outcomes": result.document_outcomes,
        "records": result.records,
        "status": result.status.value,
    }


@dataclass(frozen=True, repr=False)
class DeltaPropagationResult:
    status: DeltaPropagationStatus
    base_dataset_version: str = ""
    dataset_version: str = ""
    records: tuple[dict[str, object], ...] = ()
    count: int = 0
    metrics: DeltaPropagationMetrics | None = None
    digest: str | None = None
    document_outcomes: tuple[tuple[str, str], ...] = ()
    error_category: DeltaPropagationFailureCategory | None = None

    def __post_init__(self) -> None:
        _require_exact_fields(
            self,
            frozenset({"status", "base_dataset_version", "dataset_version", "records", "count", "metrics", "digest", "document_outcomes", "error_category"}),
        )
        if type(self.status) is not DeltaPropagationStatus:
            raise TypeError("status is invalid")
        if type(self.base_dataset_version) is not str or type(self.dataset_version) is not str:
            raise TypeError("dataset versions are invalid")
        if type(self.records) is not tuple or any(type(record) is not dict for record in self.records):
            raise TypeError("records are invalid")
        if type(self.document_outcomes) is not tuple:
            raise TypeError("document outcomes are invalid")
        previous_document_id: str | None = None
        outcome_counts = {state: 0 for state in _OUTCOME_STATES}
        for outcome in self.document_outcomes:
            if type(outcome) is not tuple or len(outcome) != 2:
                raise TypeError("document outcomes are invalid")
            document_id, state = outcome
            if type(document_id) is not str or _DOCUMENT_ID.fullmatch(document_id) is None:
                raise ValueError("document outcome identity is invalid")
            if type(state) is not str or state not in _OUTCOME_STATES:
                raise ValueError("document outcome state is invalid")
            if previous_document_id is not None and document_id <= previous_document_id:
                raise ValueError("document outcomes are not sorted and unique")
            previous_document_id = document_id
            outcome_counts[state] += 1
        if type(self.count) is not int or self.count < 0 or self.count != len(self.records):
            raise ValueError("count is invalid")
        if self.status is DeltaPropagationStatus.FAILED:
            if self.records or self.count != 0 or self.metrics is not None or self.digest is not None or self.document_outcomes:
                raise ValueError("failed result is inconsistent")
            if type(self.error_category) is not DeltaPropagationFailureCategory:
                raise ValueError("failure category is invalid")
            return
        if self.error_category is not None or type(self.metrics) is not DeltaPropagationMetrics:
            raise ValueError("success result is inconsistent")
        _opaque("base_dataset_version", self.base_dataset_version)
        _opaque("dataset_version", self.dataset_version)
        if self.base_dataset_version == self.dataset_version:
            raise ValueError("dataset versions must differ")
        try:
            copied: list[dict[str, object]] = []
            for record in self.records:
                projection = TombstoneProjectionResult(
                    status=TombstoneProjectionStatus.SUCCESS,
                    records=(record,),
                    count=1,
                    metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
                )
                copied.append(projection.records[0])
            ordered = tuple(sorted(copied, key=_record_key))
            if tuple(_record_key(record) for record in copied) != tuple(_record_key(record) for record in ordered):
                raise ValueError("records are not ordered")
            object.__setattr__(self, "records", ordered)
        except (TypeError, ValueError):
            raise ValueError("records are invalid") from None
        self.metrics.__post_init__()
        if self.metrics.document_count != len(self.document_outcomes):
            raise ValueError("document metrics are inconsistent")
        if self.metrics.new_document_count != outcome_counts["new"]:
            raise ValueError("new document metrics are inconsistent")
        if self.metrics.unchanged_document_count != outcome_counts["unchanged"]:
            raise ValueError("unchanged document metrics are inconsistent")
        if self.metrics.changed_document_count != outcome_counts["changed"]:
            raise ValueError("changed document metrics are inconsistent")
        if self.metrics.removed_document_count != outcome_counts["removed"]:
            raise ValueError("removed document metrics are inconsistent")
        if self.metrics.record_count != self.count:
            raise ValueError("record metrics are inconsistent")
        counts = {kind: sum(record["entity_type"] == kind for record in self.records) for kind in ("document", "chunk", "media", "relation", "acl", "symbol")}
        if sum(counts.values()) != self.count:
            raise ValueError("record entity types are invalid")
        if (self.metrics.document_tombstone_count != counts["document"] or self.metrics.chunk_tombstone_count != counts["chunk"] or self.metrics.media_tombstone_count != counts["media"] or self.metrics.relation_tombstone_count != counts["relation"] or self.metrics.acl_tombstone_count != counts["acl"] or self.metrics.symbol_tombstone_count != counts["symbol"]):
            raise ValueError("record metrics are inconsistent")
        if type(self.digest) is not str or _SHA256.fullmatch(self.digest) is None:
            raise ValueError("digest is invalid")
        expected = hashlib.sha256(json.dumps(_canonical_payload(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        if self.digest != expected:
            raise ValueError("digest is invalid")

    def to_bytes(self) -> bytes:
        return json.dumps(_canonical_payload(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


__all__ = [
    "DeltaInventoryEntry",
    "DeltaInventoryState",
    "DeltaPropagationFailureCategory",
    "DeltaPropagationMetrics",
    "DeltaPropagationRequest",
    "DeltaPropagationResult",
    "DeltaPropagationStatus",
]
