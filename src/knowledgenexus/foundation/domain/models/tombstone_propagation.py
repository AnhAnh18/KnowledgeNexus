"""Runtime-validated models for bounded tombstone projection."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import unicodedata

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules.tombstone_id_generator import TombstoneIdGenerator


_OPAQUE = re.compile(r"^\S+$")
_CHUNK = re.compile(r"^chunk:(?:confluence|git):[0-9a-f]{16}(?:-[0-9]+)?$")
_RELATION = re.compile(r"^rel:[0-9a-f]{16}$")
_ACL = re.compile(r"^acl:\S+$")
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_TOMBSTONE_ID = re.compile(r"^tomb:[0-9a-f]{16}$")
_MISSING = object()


def _require_exact_fields(instance: object, expected: frozenset[str]) -> None:
    try:
        actual = frozenset(vars(instance))
    except TypeError:
        raise TypeError("model fields are invalid") from None
    if actual != expected:
        raise TypeError("model fields are invalid")


class TombstoneEntityType(StrEnum):
    DOCUMENT = "document"
    CHUNK = "chunk"
    RELATION = "relation"
    ACL = "acl"
    MEDIA = "media"
    SYMBOL = "symbol"


class TombstoneReason(StrEnum):
    SOURCE_DELETED = "source_deleted"
    ACCESS_REVOKED = "access_revoked"
    MOVED_OUT_OF_SCOPE = "moved_out_of_scope"
    CONTENT_UPDATED = "content_updated"
    CONFIG_INVALIDATED = "config_invalidated"


class TombstoneProjectionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class TombstoneProjectionFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_DEPENDENCY = "invalid_dependency"
    CASCADE_INVALID = "cascade_invalid"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    TOMBSTONE_ID_COLLISION = "tombstone_id_collision"
    RESULT_INVALID = "result_invalid"
    INTERNAL_FAILURE = "internal_failure"


def _non_empty_opaque(name: str, value: object) -> str:
    if type(value) is not str or not value or _OPAQUE.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return unicodedata.normalize("NFC", value)


def _timestamp(value: object) -> str:
    if type(value) is not str or _RFC3339.fullmatch(value) is None:
        raise ValueError("detected_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("detected_at is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("detected_at is invalid")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_entity_id(entity_type: TombstoneEntityType, entity_id: str) -> str:
    value = _non_empty_opaque("entity_id", entity_id)
    pattern = {
        TombstoneEntityType.CHUNK: _CHUNK,
        TombstoneEntityType.RELATION: _RELATION,
        TombstoneEntityType.ACL: _ACL,
    }.get(entity_type)
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError("entity_id is invalid")
    return value


@dataclass(frozen=True)
class TombstoneTarget:
    entity_type: TombstoneEntityType
    entity_id: str
    detail: str | None = None
    source_version_last_seen: str | None = None

    def __post_init__(self) -> None:
        _require_exact_fields(self, frozenset({"entity_type", "entity_id", "detail", "source_version_last_seen"}))
        entity_type = getattr(self, "entity_type", _MISSING)
        entity_id = getattr(self, "entity_id", _MISSING)
        detail = getattr(self, "detail", _MISSING)
        source_version = getattr(self, "source_version_last_seen", _MISSING)
        if type(entity_type) is not TombstoneEntityType:
            raise TypeError("entity_type is invalid")
        if entity_id is _MISSING or detail is _MISSING or source_version is _MISSING:
            raise TypeError("target fields are invalid")
        object.__setattr__(self, "entity_id", _validate_entity_id(entity_type, entity_id))
        if detail is not None:
            if type(detail) is not str:
                raise TypeError("detail is invalid")
            normalized = unicodedata.normalize("NFC", detail)
            if "\n" in normalized or "\r" in normalized or len(normalized.encode("utf-8")) > 1024:
                raise ValueError("detail is invalid")
            object.__setattr__(self, "detail", normalized)
        if source_version is not None:
            object.__setattr__(
                self,
                "source_version_last_seen",
                _non_empty_opaque("source_version_last_seen", source_version),
            )


@dataclass(frozen=True)
class TombstoneProjectionRequest:
    root: TombstoneTarget
    reason: TombstoneReason
    detected_at: str
    dataset_version: str
    children: tuple[TombstoneTarget, ...] = ()

    def __post_init__(self) -> None:
        _require_exact_fields(self, frozenset({"root", "reason", "detected_at", "dataset_version", "children"}))
        root = getattr(self, "root", _MISSING)
        reason = getattr(self, "reason", _MISSING)
        detected_at = getattr(self, "detected_at", _MISSING)
        dataset_version = getattr(self, "dataset_version", _MISSING)
        children = getattr(self, "children", _MISSING)
        if type(root) is not TombstoneTarget:
            raise TypeError("root is invalid")
        if type(reason) is not TombstoneReason:
            raise TypeError("reason is invalid")
        if type(children) is not tuple or any(type(item) is not TombstoneTarget for item in children):
            raise TypeError("children are invalid")
        if detected_at is _MISSING or dataset_version is _MISSING:
            raise TypeError("request fields are invalid")
        TombstoneTarget.__post_init__(root)
        for child in children:
            TombstoneTarget.__post_init__(child)
        if root.entity_type is not TombstoneEntityType.DOCUMENT and children:
            raise ValueError("only document roots may cascade")
        object.__setattr__(self, "detected_at", _timestamp(detected_at))
        object.__setattr__(self, "dataset_version", _non_empty_opaque("dataset_version", dataset_version))
        keys: dict[tuple[TombstoneEntityType, str], TombstoneTarget] = {}
        for child in children:
            key = (child.entity_type, child.entity_id)
            previous = keys.get(key)
            if previous is not None and previous != child:
                raise ValueError("conflicting duplicate child")
            keys[key] = child


@dataclass(frozen=True)
class TombstoneProjectionMetrics:
    record_count: int
    root_count: int
    child_count: int

    def __post_init__(self) -> None:
        _require_exact_fields(self, frozenset({"record_count", "root_count", "child_count"}))
        record_count = getattr(self, "record_count", _MISSING)
        root_count = getattr(self, "root_count", _MISSING)
        child_count = getattr(self, "child_count", _MISSING)
        if any(type(value) is not int or value < 0 for value in (record_count, root_count, child_count)):
            raise ValueError("metrics are invalid")
        if root_count not in {0, 1} or record_count != root_count + child_count:
            raise ValueError("metrics are inconsistent")
        if root_count == 0 and child_count != 0:
            raise ValueError("metrics are inconsistent")


@dataclass(frozen=True, repr=False)
class TombstoneProjectionResult:
    status: TombstoneProjectionStatus
    records: tuple[dict[str, object], ...] = ()
    count: int = 0
    metrics: TombstoneProjectionMetrics | None = None
    error_category: TombstoneProjectionFailureCategory | None = None

    def __post_init__(self) -> None:
        _require_exact_fields(self, frozenset({"status", "records", "count", "metrics", "error_category"}))
        if type(self.status) is not TombstoneProjectionStatus:
            raise TypeError("status is invalid")
        if type(self.records) is not tuple or any(type(record) is not dict for record in self.records):
            raise TypeError("records are invalid")
        if type(self.count) is not int or self.count < 0:
            raise ValueError("count is invalid")
        for record in self.records:
            try:
                _validate_json_object(record)
                _validate_tombstone_record(record)
            except (TypeError, ValueError):
                raise ValueError("records are invalid") from None
        try:
            copied = tuple(copy.deepcopy(record) for record in self.records)
        except Exception:
            raise ValueError("records are invalid") from None
        object.__setattr__(self, "records", copied)
        if self.status is TombstoneProjectionStatus.SUCCESS:
            if type(self.metrics) is not TombstoneProjectionMetrics or self.error_category is not None:
                raise ValueError("success result is inconsistent")
            TombstoneProjectionMetrics.__post_init__(self.metrics)
            if self.count < 1 or self.metrics.root_count != 1:
                raise ValueError("success metrics are inconsistent")
            if self.count != len(self.records) or self.metrics.record_count != self.count:
                raise ValueError("success counts are inconsistent")
        else:
            if self.records or self.count != 0 or self.metrics is not None:
                raise ValueError("failed result is inconsistent")
            if type(self.error_category) is not TombstoneProjectionFailureCategory:
                raise ValueError("failure category is invalid")

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "count": self.count,
                "error_category": self.error_category.value if self.error_category else None,
                "metrics": self.metrics.__dict__ if self.metrics else None,
                "records": self.records,
                "status": self.status.value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


def _validate_json_object(value: object, *, _active_ids: set[int] | None = None, _depth: int = 0) -> None:
    """Reject non-canonical JSON values before they cross the result boundary."""
    if _depth > 64:
        raise ValueError("record nesting is too deep")
    if _active_ids is None:
        _active_ids = set()
    if type(value) is dict or type(value) in (list, tuple):
        identity = id(value)
        if identity in _active_ids:
            raise ValueError("record contains a cycle")
        _active_ids.add(identity)
        try:
            if type(value) is dict:
                for key, item in value.items():
                    if type(key) is not str:
                        raise TypeError("record keys are invalid")
                    _validate_json_object(item, _active_ids=_active_ids, _depth=_depth + 1)
            else:
                for item in value:
                    _validate_json_object(item, _active_ids=_active_ids, _depth=_depth + 1)
        finally:
            _active_ids.remove(identity)
        return
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        import math

        if math.isfinite(value):
            return
    raise TypeError("record value is not JSON-safe")


def _validate_tombstone_record(record: dict[str, object]) -> None:
    required = {
        "schema_version", "tombstone_id", "entity_type", "entity_id",
        "reason", "detected_at", "dataset_version",
    }
    optional = {"detail", "source_version_last_seen"}
    keys = set(record)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ValueError("record shape is invalid")
    if type(record["schema_version"]) is not str or record["schema_version"] != SCHEMA_VERSION:
        raise ValueError("record schema version is invalid")
    tombstone_id = record["tombstone_id"]
    if type(tombstone_id) is not str or _TOMBSTONE_ID.fullmatch(tombstone_id) is None:
        raise ValueError("record tombstone ID is invalid")
    try:
        entity_type = TombstoneEntityType(record["entity_type"])
        TombstoneReason(record["reason"])
    except (TypeError, ValueError):
        raise ValueError("record enum is invalid") from None
    _validate_entity_id(entity_type, record["entity_id"])
    expected_id = TombstoneIdGenerator.generate_tombstone_id(
        entity_type=entity_type.value,
        entity_id=record["entity_id"],
        reason=TombstoneReason(record["reason"]).value,
        dataset_version=record["dataset_version"],
    )
    if record["tombstone_id"] != expected_id:
        raise ValueError("record tombstone ID preimage is invalid")
    detected_at = record["detected_at"]
    if type(detected_at) is not str or _timestamp(detected_at) != detected_at:
        raise ValueError("record timestamp is invalid")
    _non_empty_opaque("dataset_version", record["dataset_version"])
    if "detail" in record:
        detail = record["detail"]
        if detail is not None and (type(detail) is not str or "\n" in detail or "\r" in detail or len(detail.encode("utf-8")) > 1024):
            raise ValueError("record detail is invalid")
    if "source_version_last_seen" in record:
        source_version = record["source_version_last_seen"]
        if source_version is not None:
            _non_empty_opaque("source_version_last_seen", source_version)


__all__ = [
    "TombstoneEntityType",
    "TombstoneProjectionFailureCategory",
    "TombstoneProjectionMetrics",
    "TombstoneProjectionRequest",
    "TombstoneProjectionResult",
    "TombstoneProjectionStatus",
    "TombstoneReason",
    "TombstoneTarget",
]
