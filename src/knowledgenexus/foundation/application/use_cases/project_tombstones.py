from __future__ import annotations

import json

from knowledgenexus.foundation.domain.models.tombstone_propagation import (
    TombstoneProjectionFailureCategory,
    TombstoneProjectionMetrics,
    TombstoneProjectionRequest,
    TombstoneProjectionResult,
    TombstoneProjectionStatus,
    TombstoneTarget,
)
from knowledgenexus.foundation.domain.rules.tombstone_record_builder import TombstoneRecordBuilder
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationValidationError


_ENTITY_RANK = {
    "document": 0,
    "chunk": 1,
    "media": 2,
    "relation": 3,
    "acl": 4,
    "symbol": 5,
}


class ProjectTombstones:
    """Materialize explicit tombstone targets atomically and deterministically."""

    def __init__(self, *, schema_validator: object) -> None:
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._validator = schema_validator

    def execute(self, request: object) -> TombstoneProjectionResult:
        try:
            if type(request) is not TombstoneProjectionRequest:
                raise _Failure(TombstoneProjectionFailureCategory.INVALID_REQUEST)
            try:
                TombstoneProjectionRequest.__post_init__(request)
            except (TypeError, ValueError):
                raise _Failure(TombstoneProjectionFailureCategory.INVALID_REQUEST) from None
            if not callable(getattr(self._validator, "validate_record", None)):
                raise _Failure(TombstoneProjectionFailureCategory.INVALID_DEPENDENCY)
            targets = (request.root, *request.children)
            unique: dict[tuple[str, str], TombstoneTarget] = {}
            for target in targets:
                key = (target.entity_type.value, target.entity_id)
                previous = unique.get(key)
                if previous is not None and previous != target:
                    raise _Failure(TombstoneProjectionFailureCategory.DUPLICATE_CONFLICT)
                unique[key] = target
            ordered = tuple(sorted(unique.values(), key=lambda target: (_ENTITY_RANK[target.entity_type.value], target.entity_id)))
            records: list[dict[str, object]] = []
            id_preimages: dict[str, bytes] = {}
            for target in ordered:
                try:
                    record = TombstoneRecordBuilder.build(
                        target=target,
                        reason=request.reason,
                        detected_at=request.detected_at,
                        dataset_version=request.dataset_version,
                        schema_validator=self._validator,
                    )
                except (FoundationValidationError, ValueError):
                    raise _Failure(
                        TombstoneProjectionFailureCategory.SCHEMA_VALIDATION_FAILED
                    ) from None
                tombstone_id = record.get("tombstone_id")
                if type(tombstone_id) is not str:
                    raise _Failure(TombstoneProjectionFailureCategory.RESULT_INVALID)
                try:
                    canonical = json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                except (TypeError, ValueError):
                    raise _Failure(TombstoneProjectionFailureCategory.RESULT_INVALID) from None
                previous = id_preimages.get(tombstone_id)
                if previous is not None and previous != canonical:
                    raise _Failure(TombstoneProjectionFailureCategory.TOMBSTONE_ID_COLLISION)
                id_preimages[tombstone_id] = canonical
                records.append(record)
            metrics = TombstoneProjectionMetrics(
                record_count=len(records),
                root_count=1,
                child_count=len(records) - 1,
            )
            return TombstoneProjectionResult(
                status=TombstoneProjectionStatus.SUCCESS,
                records=tuple(records),
                count=len(records),
                metrics=metrics,
            )
        except _Failure as exc:
            return TombstoneProjectionResult(
                status=TombstoneProjectionStatus.FAILED,
                error_category=exc.category,
            )
        except Exception:
            return TombstoneProjectionResult(
                status=TombstoneProjectionStatus.FAILED,
                error_category=TombstoneProjectionFailureCategory.INTERNAL_FAILURE,
            )


class _Failure(Exception):
    def __init__(self, category: TombstoneProjectionFailureCategory) -> None:
        self.category = category


__all__ = ["ProjectTombstones"]
