from __future__ import annotations

import copy
import json

from knowledgenexus.foundation.domain.models.tombstone_propagation import (
    TombstoneReason,
    TombstoneTarget,
)
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules.tombstone_id_generator import TombstoneIdGenerator


class TombstoneRecordBuilder:
    """Build a schema-shaped TombstoneRecord with no I/O or policy inference."""

    @classmethod
    def build(
        cls,
        *,
        target: TombstoneTarget,
        reason: TombstoneReason,
        detected_at: str,
        dataset_version: str,
        schema_validator: object,
    ) -> dict[str, object]:
        if type(target) is not TombstoneTarget:
            raise TypeError("target is invalid")
        TombstoneTarget.__post_init__(target)
        if type(reason) is not TombstoneReason:
            raise TypeError("reason is invalid")
        if type(detected_at) is not str or not detected_at:
            raise ValueError("detected_at is invalid")
        if type(dataset_version) is not str or not dataset_version or any(char.isspace() for char in dataset_version):
            raise ValueError("dataset_version is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "tombstone_id": TombstoneIdGenerator.generate_tombstone_id(
                entity_type=target.entity_type.value,
                entity_id=target.entity_id,
                reason=reason.value,
                dataset_version=dataset_version,
            ),
            "entity_type": target.entity_type.value,
            "entity_id": target.entity_id,
            "reason": reason.value,
            "detected_at": detected_at,
            "dataset_version": dataset_version,
        }
        if target.detail is not None:
            record["detail"] = target.detail
        if target.source_version_last_seen is not None:
            record["source_version_last_seen"] = target.source_version_last_seen
        before_validation = copy.deepcopy(record)
        before_bytes = json.dumps(
            before_validation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        schema_validator.validate_record("TombstoneRecord", record)
        if type(record) is not dict or set(record) != set(before_validation):
            raise ValueError("schema validator mutated record")
        for key, expected in before_validation.items():
            actual = record[key]
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError("schema validator mutated record")
        after_bytes = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if after_bytes != before_bytes:
            raise ValueError("schema validator mutated record")
        return dict(record)


__all__ = ["TombstoneRecordBuilder"]
