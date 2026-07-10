from __future__ import annotations

from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


class RelationRecordBuilder:
    """Build plain RelationRecord dicts shaped by the Foundation schema."""

    @classmethod
    def build(
        cls,
        *,
        relation_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        resolution_status: str,
        created_at: str,
        evidence: str | None = None,
        confidence: int | float | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("relation_id", relation_id)
        cls._require_non_empty_string("source_id", source_id)
        cls._require_non_empty_string("target_id", target_id)
        cls._require_non_empty_string("relation_type", relation_type)
        cls._require_non_empty_string("resolution_status", resolution_status)
        cls._require_non_empty_string("created_at", created_at)
        cls._require_optional_string("evidence", evidence)
        cls._require_optional_confidence("confidence", confidence)

        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "relation_id": relation_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "resolution_status": resolution_status,
            "created_at": created_at,
        }

        if evidence is not None:
            record["evidence"] = evidence
        if confidence is not None:
            record["confidence"] = confidence

        return record

    @staticmethod
    def _require_string(field_name: str, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"RelationRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        RelationRecordBuilder._require_string(field_name, value)
        if value == "":
            raise ValueError(f"RelationRecordBuilder.{field_name} must not be empty")

    @staticmethod
    def _require_optional_string(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"RelationRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_optional_confidence(field_name: str, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"RelationRecordBuilder.{field_name} expects number")
        if not 0 <= value <= 1:
            raise ValueError(
                f"RelationRecordBuilder.{field_name} must be between 0 and 1"
            )
