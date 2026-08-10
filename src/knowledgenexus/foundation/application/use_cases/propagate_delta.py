from __future__ import annotations

import hashlib
import json

from knowledgenexus.foundation.domain.models.chunk_stability import DocumentChunkSetSummary
from knowledgenexus.foundation.domain.models.delta_propagation import (
    DeltaInventoryEntry,
    DeltaInventoryState,
    DeltaPropagationFailureCategory,
    DeltaPropagationMetrics,
    DeltaPropagationRequest,
    DeltaPropagationResult,
    DeltaPropagationStatus,
)
from knowledgenexus.foundation.domain.models.tombstone_propagation import (
    TombstoneEntityType,
    TombstoneProjectionRequest,
    TombstoneProjectionStatus,
    TombstoneReason,
    TombstoneTarget,
)
from knowledgenexus.foundation.application.use_cases.project_tombstones import ProjectTombstones

from knowledgenexus.foundation.domain.models.delta_propagation import (
    _InventoryConflictError,
    _SummaryValidationError,
)


_ENTITY_RANK = {"document": 0, "chunk": 1, "media": 2, "relation": 3, "acl": 4, "symbol": 5}
_REASON_BY_STATE = {
    DeltaInventoryState.SOURCE_DELETED: TombstoneReason.SOURCE_DELETED,
    DeltaInventoryState.ACCESS_REVOKED: TombstoneReason.ACCESS_REVOKED,
    DeltaInventoryState.MOVED_OUT_OF_SCOPE: TombstoneReason.MOVED_OUT_OF_SCOPE,
    DeltaInventoryState.CONFIG_INVALIDATED: TombstoneReason.CONFIG_INVALIDATED,
}


class PropagateDelta:
    """Compute a deterministic, read-only tombstone delta."""

    def __init__(self, *, schema_validator: object) -> None:
        try:
            validator = getattr(schema_validator, "validate_record", None)
        except Exception:
            raise TypeError("schema_validator is invalid") from None
        if not callable(validator):
            raise TypeError("schema_validator is invalid")
        self._validator = schema_validator
        self._projector = ProjectTombstones(schema_validator=schema_validator)

    def execute(self, request: object) -> DeltaPropagationResult:
        try:
            if type(request) is not DeltaPropagationRequest:
                raise _Failure(DeltaPropagationFailureCategory.INVALID_REQUEST)
            try:
                DeltaPropagationRequest.__post_init__(request)
            except _InventoryConflictError:
                raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT) from None
            except _SummaryValidationError:
                raise _Failure(DeltaPropagationFailureCategory.SUMMARY_INVALID) from None
            except (TypeError, ValueError):
                raise _Failure(DeltaPropagationFailureCategory.INVALID_REQUEST) from None
            try:
                if not callable(getattr(self._validator, "validate_record", None)):
                    raise _Failure(DeltaPropagationFailureCategory.INVALID_DEPENDENCY)
            except Exception:
                raise _Failure(DeltaPropagationFailureCategory.INVALID_DEPENDENCY) from None

            previous = {summary.document_id: summary for summary in request.previous_summaries}
            current = {summary.document_id: summary for summary in request.current_summaries}
            inventory: dict[str, DeltaInventoryEntry] = {}
            for entry in request.inventory:
                prior = inventory.get(entry.document_id)
                if prior is not None and (
                    prior.state is not entry.state
                    or prior.source_version_last_seen != entry.source_version_last_seen
                ):
                    raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT)
                inventory[entry.document_id] = entry
            dependents = {document_id: targets for document_id, targets in request.previous_dependents}

            records: list[dict[str, object]] = []
            document_outcomes: list[tuple[str, str]] = []
            new_count = unchanged_count = changed_count = removed_count = 0
            union_ids = set(previous) | set(current)
            for inventory_id in inventory:
                if inventory_id not in union_ids:
                    raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT)
            for document_id in sorted(union_ids):
                old = previous.get(document_id)
                new = current.get(document_id)
                observation = inventory.get(document_id)

                if old is None:
                    document_outcomes.append((document_id, "new"))
                    new_count += 1
                    if observation is not None and observation.state is not DeltaInventoryState.PRESENT:
                        raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT)
                    continue

                if new is None:
                    if observation is not None and observation.state is DeltaInventoryState.PRESENT:
                        raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT)
                    removed_count += 1
                    document_outcomes.append((document_id, "removed"))
                    state = observation.state if observation is not None else DeltaInventoryState.SOURCE_DELETED
                    records.extend(
                        self._cascade(
                            old,
                            _REASON_BY_STATE[state],
                            request,
                            dependents=dependents.get(document_id, ()),
                            source_version_last_seen=observation.source_version_last_seen if observation is not None else None,
                        )
                    )
                    continue

                if observation is not None and observation.state is not DeltaInventoryState.PRESENT:
                    raise _Failure(DeltaPropagationFailureCategory.INVENTORY_CONFLICT)

                if request.previous_config_hash != request.current_config_hash:
                    changed_count += 1
                    document_outcomes.append((document_id, "changed"))
                    records.extend(
                        self._cascade(
                            old,
                            TombstoneReason.CONFIG_INVALIDATED,
                            request,
                            dependents=dependents.get(document_id, ()),
                            source_version_last_seen=observation.source_version_last_seen if observation is not None else None,
                        )
                    )
                    continue

                if old.document_content_hash == new.document_content_hash:
                    unchanged_count += 1
                    document_outcomes.append((document_id, "unchanged"))
                    continue

                changed_count += 1
                document_outcomes.append((document_id, "changed"))
                current_entries = {entry.chunk_id: entry for entry in new.entries}
                for entry in sorted(old.entries, key=lambda item: item.chunk_id):
                    counterpart = current_entries.get(entry.chunk_id)
                    if counterpart is None or counterpart.content_hash != entry.content_hash:
                        records.extend(self._chunk_tombstone(entry.chunk_id, request))

            records = self._deduplicate_and_sort(records)
            document_tombstones = sum(record["entity_type"] == "document" for record in records)
            chunk_tombstones = sum(record["entity_type"] == "chunk" for record in records)
            media_tombstones = sum(record["entity_type"] == "media" for record in records)
            relation_tombstones = sum(record["entity_type"] == "relation" for record in records)
            acl_tombstones = sum(record["entity_type"] == "acl" for record in records)
            symbol_tombstones = sum(record["entity_type"] == "symbol" for record in records)
            metrics = DeltaPropagationMetrics(
                document_count=len(union_ids),
                new_document_count=new_count,
                unchanged_document_count=unchanged_count,
                changed_document_count=changed_count,
                removed_document_count=removed_count,
                document_tombstone_count=document_tombstones,
                chunk_tombstone_count=chunk_tombstones,
                record_count=len(records),
                media_tombstone_count=media_tombstones,
                relation_tombstone_count=relation_tombstones,
                acl_tombstone_count=acl_tombstones,
                symbol_tombstone_count=symbol_tombstones,
            )
            payload = {
                "base_dataset_version": request.previous_dataset_version,
                "count": len(records),
                "dataset_version": request.current_dataset_version,
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
                },
                "document_outcomes": tuple(document_outcomes),
                "records": tuple(records),
                "status": DeltaPropagationStatus.SUCCESS.value,
            }
            digest = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest()
            return DeltaPropagationResult(
                status=DeltaPropagationStatus.SUCCESS,
                base_dataset_version=request.previous_dataset_version,
                dataset_version=request.current_dataset_version,
                records=tuple(records),
                count=len(records),
                metrics=metrics,
                digest=digest,
                document_outcomes=tuple(document_outcomes),
            )
        except _Failure as exc:
            return DeltaPropagationResult(
                status=DeltaPropagationStatus.FAILED,
                error_category=exc.category,
            )
        except Exception:
            return DeltaPropagationResult(
                status=DeltaPropagationStatus.FAILED,
                error_category=DeltaPropagationFailureCategory.INTERNAL_FAILURE,
            )

    def _cascade(
        self,
        summary: DocumentChunkSetSummary,
        reason: TombstoneReason,
        request: DeltaPropagationRequest,
        *,
        source_version_last_seen: str | None = None,
        dependents: tuple[TombstoneTarget, ...] = (),
    ) -> list[dict[str, object]]:
        root = TombstoneTarget(
            TombstoneEntityType.DOCUMENT,
            summary.document_id,
            source_version_last_seen=source_version_last_seen,
        )
        children = tuple(TombstoneTarget(TombstoneEntityType.CHUNK, entry.chunk_id) for entry in summary.entries) + tuple(dependents)
        result = self._projector.execute(
            TombstoneProjectionRequest(
                root=root,
                reason=reason,
                detected_at=request.detected_at,
                dataset_version=request.current_dataset_version,
                children=children,
            )
        )
        if result.status is not TombstoneProjectionStatus.SUCCESS:
            raise _Failure(DeltaPropagationFailureCategory.TOMBSTONE_FAILURE)
        return list(result.records)

    def _chunk_tombstone(self, chunk_id: str, request: DeltaPropagationRequest) -> list[dict[str, object]]:
        result = self._projector.execute(
            TombstoneProjectionRequest(
                root=TombstoneTarget(TombstoneEntityType.CHUNK, chunk_id),
                reason=TombstoneReason.CONTENT_UPDATED,
                detected_at=request.detected_at,
                dataset_version=request.current_dataset_version,
            )
        )
        if result.status is not TombstoneProjectionStatus.SUCCESS:
            raise _Failure(DeltaPropagationFailureCategory.TOMBSTONE_FAILURE)
        return list(result.records)

    @staticmethod
    def _deduplicate_and_sort(records: list[dict[str, object]]) -> list[dict[str, object]]:
        by_id: dict[str, tuple[bytes, dict[str, object]]] = {}
        for record in records:
            tombstone_id = record.get("tombstone_id")
            if type(tombstone_id) is not str:
                raise _Failure(DeltaPropagationFailureCategory.RESULT_INVALID)
            try:
                canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            except (TypeError, ValueError):
                raise _Failure(DeltaPropagationFailureCategory.RESULT_INVALID) from None
            prior = by_id.get(tombstone_id)
            if prior is not None and prior[0] != canonical:
                raise _Failure(DeltaPropagationFailureCategory.RESULT_INVALID)
            by_id[tombstone_id] = (canonical, record)
        values = [item[1] for item in by_id.values()]
        values.sort(key=lambda record: (_ENTITY_RANK.get(record.get("entity_type", ""), 99), record.get("entity_id", ""), record.get("tombstone_id", "")))
        return values


class _Failure(Exception):
    def __init__(self, category: DeltaPropagationFailureCategory) -> None:
        self.category = category


__all__ = ["PropagateDelta"]
