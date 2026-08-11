"""Bounded orchestration for a second M10 snapshot.

The exporter owns publication; this seam only compares an already published
stream (obtained through an explicit reader) with the current in-memory M10
projection.  It deliberately performs no filesystem or network I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from knowledgenexus.foundation.application.use_cases.propagate_delta import PropagateDelta
from knowledgenexus.foundation.domain.models.chunk_stability import (
    ACTIVE_CHUNKER_VERSION,
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ChunkStabilityEntry,
    DocumentChunkSetSummary,
)
from knowledgenexus.foundation.domain.models.delta_propagation import (
    DeltaInventoryEntry,
    DeltaInventoryState,
    DeltaPropagationRequest,
    DeltaPropagationResult,
    DeltaPropagationStatus,
)
from knowledgenexus.foundation.domain.models.delta_inventory import _validate_w4_entry
from knowledgenexus.foundation.domain.models.m10_snapshot import (
    M10SnapshotProjection,
    M10SnapshotRequest,
)
from knowledgenexus.foundation.domain.models.tombstone_propagation import (
    TombstoneEntityType,
    TombstoneTarget,
)
from knowledgenexus.foundation.domain.rules.dataset_version_generator import DatasetVersionGenerator
from knowledgenexus.foundation.domain.rules.snapshot_readback import (
    SnapshotReadbackError,
    validate_snapshot_streams,
)


_STREAMS = ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
_STREAM_IDS = {
    "documents": "document_id",
    "chunks": "chunk_id",
    "relations": "relation_id",
    "acl": "acl_id",
    "media_assets": "media_id",
    "symbols": "symbol_id",
    "sync_state": "entity_id",
    "tombstones": "tombstone_id",
}


class M10DeltaOrchestrationError(ValueError):
    """Sanitized failure at the M10 delta composition boundary."""


@dataclass(frozen=True)
class M10DeltaOrchestrationResult:
    projection: M10SnapshotProjection
    propagation: DeltaPropagationResult
    base_streams: dict[str, tuple[dict[str, object], ...]]

    def __post_init__(self) -> None:
        if type(self.projection) is not M10SnapshotProjection or type(self.propagation) is not DeltaPropagationResult:
            raise TypeError("delta result is invalid")
        if type(self.base_streams) is not dict:
            raise TypeError("delta base streams are invalid")
        try:
            _stream_view(self.base_streams)
        except Exception:
            raise TypeError("delta base streams are invalid") from None


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _stream_view(value: object) -> dict[str, tuple[dict[str, object], ...]]:
    """Copy a reader result without retaining mutable or proxy-backed rows."""
    streams = getattr(value, "streams", value)
    if type(streams) is not dict and not isinstance(streams, Mapping):
        raise M10DeltaOrchestrationError("prior snapshot streams are invalid")
    if set(streams) != set(_STREAMS):
        raise M10DeltaOrchestrationError("prior snapshot streams are incomplete")
    result: dict[str, tuple[dict[str, object], ...]] = {}
    for name in _STREAMS:
        rows = streams[name]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise M10DeltaOrchestrationError("prior snapshot stream is invalid")
        copied: list[dict[str, object]] = []
        identity_field = _STREAM_IDS[name]
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping) or any(type(key) is not str for key in row):
                raise M10DeltaOrchestrationError("prior snapshot record is invalid")
            record = dict(row)
            identity = record.get(identity_field)
            if type(identity) is not str or not identity or identity in seen_ids:
                raise M10DeltaOrchestrationError("prior snapshot identity is invalid")
            seen_ids.add(identity)
            copied.append(record)
        result[name] = tuple(copied)
    return result


def _reader_result(reader: object, base_dataset_version: str) -> object:
    try:
        if callable(reader):
            return reader(base_dataset_version)
        read = getattr(reader, "read", None)
        if callable(read):
            return read(base_dataset_version)
    except Exception:
        raise M10DeltaOrchestrationError("prior snapshot read failed") from None
    raise M10DeltaOrchestrationError("prior snapshot reader is invalid")


def _records_by_document(streams: Mapping[str, Sequence[Mapping[str, object]]]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for row in streams["documents"]:
        document_id = row.get("document_id")
        if type(document_id) is not str or document_id in records:
            raise M10DeltaOrchestrationError("document identity is invalid")
        records[document_id] = dict(row)
    return records


def _summary_stream(streams: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[DocumentChunkSetSummary, ...]:
    documents = _records_by_document(streams)
    chunks_by_document: dict[str, list[ChunkStabilityEntry]] = {document_id: [] for document_id in documents}
    for row in streams["chunks"]:
        document_id = row.get("document_id")
        if document_id not in chunks_by_document:
            raise M10DeltaOrchestrationError("chunk parent is invalid")
        try:
            chunks_by_document[document_id].append(
                ChunkStabilityEntry(
                    row["chunk_id"],
                    row["content_hash"],
                    row["content_kind"],
                    row["token_count"],
                    row.get("part_index"),
                    row.get("part_total"),
                )
            )
        except Exception:
            raise M10DeltaOrchestrationError("chunk stability data is invalid") from None

    summaries: list[DocumentChunkSetSummary] = []
    for document_id in sorted(documents):
        entries = tuple(sorted(chunks_by_document[document_id], key=lambda entry: entry.chunk_id))
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.content_kind] = counts.get(entry.content_kind, 0) + 1
        try:
            summaries.append(
                DocumentChunkSetSummary(
                    format_version="1",
                    document_id=document_id,
                    document_content_hash=documents[document_id]["content_hash"],
                    chunker_version=ACTIVE_CHUNKER_VERSION,
                    profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
                    entries=entries,
                    chunk_count=len(entries),
                    content_kind_counts=tuple(sorted(counts.items())),
                )
            )
        except Exception:
            raise M10DeltaOrchestrationError("document stability data is invalid") from None
    return tuple(summaries)


def _acl_fingerprints(streams: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for row in streams["acl"]:
        document_id = row.get("document_id")
        if type(document_id) is not str:
            raise M10DeltaOrchestrationError("ACL document identity is invalid")
        semantic = {
            "acl_id": row.get("acl_id"),
            "acl_tags": row.get("acl_tags"),
            "document_id": document_id,
            "is_restricted": row.get("is_restricted"),
            "source_system": row.get("source_system"),
        }
        result.append((document_id, _canonical_hash(semantic)))
    return tuple(sorted(result))


def _chunk_records(streams: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[dict[str, object], ...]:
    return tuple(sorted((dict(row) for row in streams["chunks"]), key=lambda row: str(row.get("chunk_id", ""))))


def _targets_by_document(streams: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[tuple[str, tuple[TombstoneTarget, ...]], ...]:
    documents = _records_by_document(streams)
    chunks = {row.get("chunk_id"): row.get("document_id") for row in streams["chunks"]}
    git_documents = {
        (row.get("repo"), row.get("branch"), row.get("source_version"), row.get("file_path")): document_id
        for document_id, row in documents.items()
        if row.get("source_system") == "git"
    }
    targets: dict[str, dict[tuple[TombstoneEntityType, str], TombstoneTarget]] = {document_id: {} for document_id in documents}

    def add(document_id: object, entity_type: TombstoneEntityType, entity_id: object) -> None:
        if type(document_id) is not str or document_id not in targets or type(entity_id) is not str:
            return
        try:
            target = TombstoneTarget(entity_type, entity_id)
        except Exception:
            raise M10DeltaOrchestrationError("dependent identity is invalid") from None
        targets[document_id][(entity_type, entity_id)] = target

    for row in streams["acl"]:
        add(row.get("document_id"), TombstoneEntityType.ACL, row.get("acl_id"))
    for row in streams["media_assets"]:
        add(row.get("parent_document_id"), TombstoneEntityType.MEDIA, row.get("media_id"))
    for row in streams["symbols"]:
        owner = row.get("document_id") or chunks.get(row.get("chunk_id"))
        if owner is None:
            owner = git_documents.get(
                (row.get("repo"), row.get("branch"), row.get("commit_hash"), row.get("file_path"))
            )
        add(owner, TombstoneEntityType.SYMBOL, row.get("symbol_id"))
    for row in streams["relations"]:
        relation_id = row.get("relation_id")
        owner = row.get("source_id")
        add(chunks.get(owner, owner), TombstoneEntityType.RELATION, relation_id)
        if row.get("resolution_status") == "resolved":
            add(row.get("target_id"), TombstoneEntityType.RELATION, relation_id)
    return tuple(
        (document_id, tuple(targets[document_id][key] for key in sorted(targets[document_id], key=lambda item: (item[0].value, item[1]))))
        for document_id in sorted(targets)
    )


def _merge_tombstones(existing: Sequence[Mapping[str, object]], generated: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    by_id: dict[str, dict[str, object]] = {}
    for row in tuple(existing) + tuple(generated):
        if not isinstance(row, Mapping) or type(row.get("tombstone_id")) is not str:
            raise M10DeltaOrchestrationError("tombstone record is invalid")
        copied = dict(row)
        prior = by_id.get(copied["tombstone_id"])
        if prior is not None and prior != copied:
            raise M10DeltaOrchestrationError("conflicting tombstone record")
        by_id[copied["tombstone_id"]] = copied
    return tuple(sorted(by_id.values(), key=lambda row: (str(row.get("entity_type")), str(row.get("entity_id")), row["tombstone_id"])))


def _sparse_streams(
    prior: Mapping[str, Sequence[Mapping[str, object]]],
    current: Mapping[str, Sequence[Mapping[str, object]]],
    propagation: DeltaPropagationResult,
    tombstones: tuple[dict[str, object], ...],
    *,
    config_invalidated: bool = False,
) -> dict[str, tuple[dict[str, object], ...]]:
    outcomes = dict(propagation.document_outcomes)
    changed_docs = {doc_id for doc_id, outcome in outcomes.items() if outcome in {"new", "changed"}}
    prior_documents = {row.get("document_id"): row for row in prior["documents"]}
    current_documents = {row.get("document_id"): row for row in current["documents"]}
    acl_only_docs = {
        doc_id for doc_id in propagation.reemit_document_ids
        if doc_id in prior_documents and doc_id in current_documents
        and prior_documents[doc_id].get("content_hash") == current_documents[doc_id].get("content_hash")
    }
    changed_docs -= acl_only_docs
    reemit_chunks = {row["chunk_id"] for row in propagation.reemit_chunk_records}
    reemit_acls = {row["acl_id"] for row in propagation.reemit_acl_records}
    old_by_stream = {
        name: {row[_STREAM_IDS[name]]: row for row in prior[name]}
        for name in _STREAMS
    }
    current_chunks = {row.get("chunk_id"): row.get("document_id") for row in current["chunks"]}
    affected_ids = changed_docs | acl_only_docs
    out: dict[str, tuple[dict[str, object], ...]] = {}
    for name in _STREAMS:
        if name == "tombstones":
            out[name] = tombstones
            continue
        id_field = _STREAM_IDS[name]
        rows: list[dict[str, object]] = []
        for row in current[name]:
            identity = row.get(id_field)
            prior_row = old_by_stream[name].get(identity)
            canonical_changed = prior_row is None or _canonical_bytes(prior_row) != _canonical_bytes(row)
            belongs = row.get("document_id") in affected_ids or row.get("parent_document_id") in affected_ids
            if name == "relations":
                belongs = belongs or current_chunks.get(row.get("source_id")) in affected_ids or current_chunks.get(row.get("target_id")) in affected_ids
            if name == "sync_state":
                belongs = row.get("entity_id") in affected_ids or prior_row is None
            if name == "documents":
                belongs = identity in changed_docs
            if name == "chunks" and identity in reemit_chunks:
                belongs = True
            if name == "acl" and identity in reemit_acls:
                belongs = True
            if config_invalidated:
                belongs = True
            if not belongs and not canonical_changed:
                continue
            if name == "documents" and not config_invalidated and identity not in changed_docs and not canonical_changed:
                continue
            rows.append(dict(row))
        rows.sort(key=lambda row: str(row.get(id_field, "")))
        out[name] = tuple(rows)
    return out


class M10DeltaOrchestrator:
    """Turn a prior published stream and current M10 projection into a delta."""

    def __init__(self, *, prior_snapshot_reader: object, schema_validator: object) -> None:
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema validator is invalid")
        if not callable(prior_snapshot_reader) and not callable(getattr(prior_snapshot_reader, "read", None)):
            raise TypeError("prior snapshot reader is invalid")
        self._reader = prior_snapshot_reader
        self._propagator = PropagateDelta(schema_validator=schema_validator, require_inventory=True)

    def execute(
        self,
        request: object,
        projection: object,
        *,
        inventory: tuple[DeltaInventoryEntry, ...] = (),
    ) -> M10DeltaOrchestrationResult:
        if type(request) is not M10SnapshotRequest or type(projection) is not M10SnapshotProjection:
            raise M10DeltaOrchestrationError("M10 delta input is invalid")
        if request.export_mode != "delta" or projection.export_mode != "delta" or request.base_dataset_version is None:
            raise M10DeltaOrchestrationError("delta export is required")
        try:
            M10SnapshotRequest.__post_init__(request)
            M10SnapshotProjection.__post_init__(projection)
        except Exception:
            raise M10DeltaOrchestrationError("M10 delta input is invalid") from None
        prior_result = _reader_result(self._reader, request.base_dataset_version)
        try:
            prior = _stream_view(prior_result)
            prior_manifest = getattr(prior_result, "manifest", {})
        except M10DeltaOrchestrationError:
            raise
        except Exception:
            raise M10DeltaOrchestrationError("prior snapshot read failed") from None
        current = {name: tuple(dict(row) for row in getattr(projection, name)) for name in _STREAMS}
        # W4-B is intentionally Confluence-only.  A missing Git row cannot be
        # interpreted as a source deletion by the Confluence inventory path.
        for streams in (prior, current):
            for row in streams["documents"]:
                if row.get("source_system") != "confluence":
                    raise M10DeltaOrchestrationError("non-Confluence document is invalid")
        prior_document_ids = {row["document_id"] for row in prior["documents"]}
        current_document_ids = {row["document_id"] for row in current["documents"]}
        if type(inventory) is not tuple:
            raise M10DeltaOrchestrationError("inventory is invalid")
        inventory_by_id: dict[str, DeltaInventoryEntry] = {}
        for entry in inventory:
            if type(entry) is not DeltaInventoryEntry:
                raise M10DeltaOrchestrationError("inventory is invalid")
            try:
                _validate_w4_entry(entry)
            except Exception:
                raise M10DeltaOrchestrationError("inventory is invalid") from None
            if entry.document_id in inventory_by_id:
                raise M10DeltaOrchestrationError("inventory is conflicting")
            if entry.state is DeltaInventoryState.CONFIG_INVALIDATED:
                raise M10DeltaOrchestrationError("inventory state is invalid")
            if not entry.document_id.startswith("confluence:page:"):
                raise M10DeltaOrchestrationError("inventory document identity is invalid")
            if entry.state is not DeltaInventoryState.PRESENT and (type(entry.source_version_last_seen) is not str or not entry.source_version_last_seen):
                raise M10DeltaOrchestrationError("inventory source version is invalid")
            if entry.state is DeltaInventoryState.SOURCE_DELETED and entry.detail != "confluence_404_may_mask_access_revoked":
                raise M10DeltaOrchestrationError("inventory detail is invalid")
            if entry.state is DeltaInventoryState.PRESENT and (entry.source_version_last_seen is not None or entry.detail is not None):
                raise M10DeltaOrchestrationError("inventory present fields are invalid")
            if entry.state in {DeltaInventoryState.ACCESS_REVOKED, DeltaInventoryState.MOVED_OUT_OF_SCOPE} and entry.detail is not None:
                raise M10DeltaOrchestrationError("inventory detail is invalid")
            inventory_by_id[entry.document_id] = entry
        relevant_ids = prior_document_ids | current_document_ids
        if set(inventory_by_id) != relevant_ids:
            raise M10DeltaOrchestrationError("inventory closure is incomplete")
        for document_id in relevant_ids:
            present = document_id in current_document_ids
            state = inventory_by_id[document_id].state
            if present != (state is DeltaInventoryState.PRESENT):
                raise M10DeltaOrchestrationError("inventory state is inconsistent")
        if not isinstance(prior_manifest, Mapping):
            raise M10DeltaOrchestrationError("prior snapshot manifest is invalid")
        if prior_manifest.get("dataset_version") != request.base_dataset_version:
            raise M10DeltaOrchestrationError("prior dataset version mismatch")
        # Stability summaries are pinned to the active chunker/profile. Do not
        # compare an older snapshot as if it used the same chunk semantics.
        if prior_manifest.get("chunker_version") != projection.chunker_version:
            raise M10DeltaOrchestrationError("prior chunker version mismatch")
        try:
            current_version = DatasetVersionGenerator.generate(instant=datetime.fromisoformat(request.generated_at.replace("Z", "+00:00")))
        except Exception:
            raise M10DeltaOrchestrationError("current dataset version is invalid") from None
        previous_config_hash = prior_manifest.get("config_hash")
        if type(previous_config_hash) is not str:
            raise M10DeltaOrchestrationError("prior config hash is invalid")
        try:
            prior_mode = prior_manifest.get("export_mode", "full_snapshot") if isinstance(prior_manifest, Mapping) else "full_snapshot"
            if prior_mode not in {"full_snapshot", "delta"}:
                raise ValueError
            validate_snapshot_streams(prior, export_mode=prior_mode)
            validate_snapshot_streams(
                current,
                export_mode="delta",
                prior_streams=prior,
            )
        except (SnapshotReadbackError, TypeError, ValueError):
            raise M10DeltaOrchestrationError("snapshot streams are invalid") from None
        propagation_request = DeltaPropagationRequest(
            previous_dataset_version=request.base_dataset_version,
            current_dataset_version=current_version,
            previous_config_hash=previous_config_hash,
            current_config_hash=projection.config_hash,
            detected_at=request.generated_at,
            previous_summaries=_summary_stream(prior),
            current_summaries=_summary_stream(current),
            inventory=tuple(inventory),
            previous_dependents=_targets_by_document(prior),
            current_dependents=_targets_by_document(current),
            previous_acl_hashes=_acl_fingerprints(prior),
            current_acl_hashes=_acl_fingerprints(current),
            previous_acl_records=tuple(dict(row) for row in prior["acl"]),
            current_acl_records=tuple(dict(row) for row in current["acl"]),
            previous_chunk_records=_chunk_records(prior),
            current_chunk_records=_chunk_records(current),
        )
        result = self._propagator.execute(propagation_request)
        if result.status is not DeltaPropagationStatus.SUCCESS:
            raise M10DeltaOrchestrationError("delta propagation failed")
        tombstones = _merge_tombstones(current["tombstones"], result.records)
        sparse = _sparse_streams(
            prior,
            current,
            result,
            tombstones,
            config_invalidated=previous_config_hash != projection.config_hash,
        )
        emitted_counts = {name: len(sparse[name]) for name in _STREAMS}
        metrics = replace(
            projection.metrics,
            documents=emitted_counts["documents"],
            chunks=emitted_counts["chunks"],
            relations=emitted_counts["relations"],
            acl=emitted_counts["acl"],
            media_assets=emitted_counts["media_assets"],
            symbols=emitted_counts["symbols"],
            sync_state=emitted_counts["sync_state"],
            tombstones=emitted_counts["tombstones"],
            confluence_documents=sum(row.get("source_system") == "confluence" for row in sparse["documents"]),
            git_documents=sum(row.get("source_system") == "git" for row in sparse["documents"]),
            unresolved_relations=sum(row.get("resolution_status") != "resolved" for row in sparse["relations"]),
            media_processed=sum(row.get("processing_status") in {"parsed", "ocr", "summarized"} for row in sparse["media_assets"]),
            media_failed=sum(row.get("processing_status") == "failed" for row in sparse["media_assets"]),
            symbols_resolved=sum(row.get("chunk_id") is not None for row in sparse["symbols"]),
            default_deny_chunks=sum(row.get("acl_tags") == ["restricted:unresolved"] for row in sparse["chunks"]),
        )
        next_projection = replace(projection, **sparse, metrics=metrics)
        return M10DeltaOrchestrationResult(projection=next_projection, propagation=result, base_streams=prior)


__all__ = ["M10DeltaOrchestrationError", "M10DeltaOrchestrationResult", "M10DeltaOrchestrator"]
