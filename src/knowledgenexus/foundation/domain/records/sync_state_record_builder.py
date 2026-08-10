from __future__ import annotations

import re
from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_ENTITY_TYPES = frozenset({"page", "attachment", "file", "repo"})
_STATUSES = frozenset({"active", "tombstoned", "error"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SyncStateRecordBuilder:
    """Build schema-valid exported snapshots of authoritative sync state."""

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        entity_id: str,
        entity_type: str,
        last_synced_at: str,
        status: str = "active",
        last_seen_version: str | None = None,
        last_content_hash: str | None = None,
        schema_validator: object | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("source_id", source_id)
        cls._require_non_empty_string("entity_id", entity_id)
        if type(entity_type) is not str or entity_type not in _ENTITY_TYPES:
            raise ValueError("SyncStateRecordBuilder.entity_type is invalid")
        cls._require_non_empty_string("last_synced_at", last_synced_at)
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("SyncStateRecordBuilder.status is invalid")
        if last_seen_version is not None:
            cls._require_non_empty_string("last_seen_version", last_seen_version)
        if last_content_hash is not None:
            if type(last_content_hash) is not str or _HEX64.fullmatch(last_content_hash) is None:
                raise ValueError("SyncStateRecordBuilder.last_content_hash is invalid")

        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "source_id": source_id,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "last_seen_version": last_seen_version,
            "last_content_hash": last_content_hash,
            "last_synced_at": last_synced_at,
            "status": status,
        }
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("SyncStateRecordBuilder.schema_validator is invalid")
        try:
            validator.validate_record("SyncStateRecord", record)
        except Exception:
            raise ValueError("SyncStateRecordBuilder produced an invalid record") from None
        return record

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        if type(value) is not str or not value:
            raise ValueError(f"SyncStateRecordBuilder.{field_name} is invalid")


__all__ = ["SyncStateRecordBuilder"]
