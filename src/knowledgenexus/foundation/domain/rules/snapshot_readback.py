"""Independent cross-stream validation for published Foundation snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_STREAMS = ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
_IDS = {
    "documents": "document_id", "chunks": "chunk_id", "relations": "relation_id", "acl": "acl_id",
    "media_assets": "media_id", "symbols": "symbol_id", "sync_state": "entity_id", "tombstones": "tombstone_id",
}


class SnapshotReadbackError(ValueError):
    """Sanitized cross-stream readback failure."""


@dataclass(frozen=True)
class SnapshotClosureReport:
    """Small, non-content result suitable for a gate envelope."""

    stream_counts: tuple[tuple[str, int], ...]
    relation_closed: bool
    acl_closed: bool
    sync_closed: bool
    tombstone_closed: bool


def validate_snapshot_streams(
    streams: object,
    *,
    export_mode: str,
    prior_streams: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
) -> SnapshotClosureReport:
    """Validate cross-stream identity and ownership without mutating input."""
    if not isinstance(streams, Mapping) or set(streams) != set(_STREAMS):
        raise SnapshotReadbackError("stream set is invalid")
    if export_mode not in {"full_snapshot", "delta"}:
        raise SnapshotReadbackError("export mode is invalid")
    normalized: dict[str, tuple[dict[str, object], ...]] = {}
    for name in _STREAMS:
        value = streams[name]
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise SnapshotReadbackError("stream type is invalid")
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in value:
            if not isinstance(row, Mapping):
                raise SnapshotReadbackError("stream record is invalid")
            record = dict(row)
            identity = record.get(_IDS[name])
            if type(identity) is not str or not identity or identity in seen:
                raise SnapshotReadbackError("stream identity is invalid")
            seen.add(identity)
            rows.append(record)
        normalized[name] = tuple(rows)

    document_ids = {row["document_id"] for row in normalized["documents"]}
    chunk_ids = {row["chunk_id"] for row in normalized["chunks"]}
    relation_ids = {row["relation_id"] for row in normalized["relations"]}
    media_ids = {row["media_id"] for row in normalized["media_assets"]}
    entity_ids = document_ids | chunk_ids | media_ids

    acl_by_document: dict[str, dict[str, object]] = {}
    for row in normalized["acl"]:
        document_id = row.get("document_id")
        document = next((item for item in normalized["documents"] if item["document_id"] == document_id), None)
        if document_id not in document_ids or document_id in acl_by_document or row.get("acl_id") != document.get("acl_id") or row.get("source_system") != document.get("source_system"):
            raise SnapshotReadbackError("ACL closure is invalid")
        acl_by_document[document_id] = row
    if set(acl_by_document) != document_ids:
        raise SnapshotReadbackError("ACL closure is incomplete")

    for row in normalized["chunks"]:
        document_id = row.get("document_id")
        if document_id not in document_ids:
            raise SnapshotReadbackError("chunk parent is missing")
        parent = next(item for item in normalized["documents"] if item["document_id"] == document_id)
        if row.get("source_system") != parent.get("source_system"):
            raise SnapshotReadbackError("chunk source ownership is invalid")
        if row.get("acl_tags") != acl_by_document[document_id].get("acl_tags"):
            raise SnapshotReadbackError("chunk ACL inheritance is invalid")

    def _relation_refs(row: dict[str, object]) -> None:
        references = row.get("relation_ids", [])
        if not isinstance(references, Sequence) or isinstance(references, (str, bytes, bytearray)):
            raise SnapshotReadbackError("relation references are invalid")
        references = tuple(references)
        try:
            duplicate = len(references) != len(set(references))
        except TypeError:
            raise SnapshotReadbackError("relation references are invalid") from None
        if duplicate or any(type(value) is not str or value not in relation_ids for value in references):
            raise SnapshotReadbackError("relation closure is invalid")

    for row in normalized["documents"]:
        _relation_refs(row)
    for row in normalized["chunks"]:
        _relation_refs(row)

    relation_owners = document_ids | chunk_ids
    for row in normalized["relations"]:
        source_id = row.get("source_id")
        target_id = row.get("target_id")
        if source_id not in relation_owners or type(target_id) is not str or not target_id or row.get("resolution_status") not in {"resolved", "unresolved_without_jira_api", "deferred_mvp", "unresolved_target"}:
            raise SnapshotReadbackError("relation source/target is invalid")
        if row.get("resolution_status") == "resolved" and target_id not in entity_ids:
            raise SnapshotReadbackError("resolved relation target is missing")
        if row.get("resolution_status") != "resolved" and target_id in entity_ids:
            raise SnapshotReadbackError("unresolved relation target is emitted")
        if row.get("relation_type") == "embeds_media" and row.get("resolution_status") == "resolved":
            media = next((item for item in normalized["media_assets"] if item["media_id"] == target_id), None)
            if media is None or media.get("parent_document_id") != source_id:
                raise SnapshotReadbackError("media relation ownership is invalid")
        if row.get("relation_type") in {"includes_page", "links_to_page"} and row.get("resolution_status") == "resolved":
            source = next((item for item in normalized["documents"] if item["document_id"] == source_id), None)
            target = next((item for item in normalized["documents"] if item["document_id"] == target_id), None)
            if source is None or target is None or source.get("source_system") != "confluence" or target.get("source_system") != "confluence":
                raise SnapshotReadbackError("page relation ownership is invalid")
    relation_owners_rows = {row["document_id"]: row for row in normalized["documents"]}
    relation_owners_rows.update({row["chunk_id"]: row for row in normalized["chunks"]})
    for row in normalized["relations"]:
        owner = relation_owners_rows.get(row["source_id"])
        if owner is None or row["relation_id"] not in owner.get("relation_ids", []):
            raise SnapshotReadbackError("relation owner linkage is invalid")

    for row in normalized["media_assets"]:
        if row.get("parent_document_id") not in document_ids:
            raise SnapshotReadbackError("media parent is missing")
    git_files = {
        (row.get("repo"), row.get("branch"), row.get("source_version"), row.get("file_path"))
        for row in normalized["documents"]
        if row.get("source_system") == "git"
    }
    for row in normalized["symbols"]:
        # SymbolRecord has no document_id; provenance is keyed to its Git file.
        if (row.get("repo"), row.get("branch"), row.get("commit_hash"), row.get("file_path")) not in git_files:
            raise SnapshotReadbackError("symbol document is missing")
        if row.get("chunk_id") is not None and row.get("chunk_id") not in chunk_ids:
            raise SnapshotReadbackError("symbol chunk is missing")

    sync_ids: set[str] = set()
    for row in normalized["sync_state"]:
        entity_id = row.get("entity_id")
        entity_type = row.get("entity_type")
        expected_type = "page" if entity_id in document_ids and str(entity_id).startswith("confluence:page:") else "file" if entity_id in document_ids else "attachment" if entity_id in media_ids else "repo"
        if entity_id in sync_ids or row.get("schema_version") != "1.0" or row.get("status") != "active" or entity_type != expected_type or (entity_id not in entity_ids and entity_type != "repo"):
            raise SnapshotReadbackError("sync entity is missing")
        sync_ids.add(entity_id)
    tombstone_ids = {row["tombstone_id"] for row in normalized["tombstones"]}
    if len(tombstone_ids) != len(normalized["tombstones"]):
        raise SnapshotReadbackError("tombstone identity is invalid")
    if export_mode == "full_snapshot" and normalized["tombstones"]:
        raise SnapshotReadbackError("full snapshot contains tombstones")
    if prior_streams is not None:
        if not isinstance(prior_streams, Mapping) or set(prior_streams) != set(_STREAMS):
            raise SnapshotReadbackError("prior stream set is invalid")
        if any(
            not isinstance(prior_streams[name], Sequence)
            or isinstance(prior_streams[name], (str, bytes, bytearray))
            for name in _STREAMS
        ):
            raise SnapshotReadbackError("prior stream type is invalid")
        prior_ids: set[str] = set()
        # Tombstones are delta metadata; they are not valid targets for a
        # subsequent tombstone and therefore are excluded from the entity set.
        for name in _STREAMS:
            if name == "tombstones":
                continue
            identity_field = _IDS[name]
            for row in prior_streams[name]:
                if not isinstance(row, Mapping):
                    raise SnapshotReadbackError("prior stream record is invalid")
                identity = row.get(identity_field)
                if type(identity) is not str or not identity:
                    raise SnapshotReadbackError("prior stream identity is invalid")
                prior_ids.add(identity)
        if any(row.get("entity_id") not in prior_ids for row in normalized["tombstones"]):
            raise SnapshotReadbackError("tombstone target is not in prior snapshot")

    return SnapshotClosureReport(
        stream_counts=tuple(sorted((name, len(normalized[name])) for name in _STREAMS)),
        relation_closed=True,
        acl_closed=True,
        sync_closed=True,
        tombstone_closed=True,
    )


__all__ = ["SnapshotClosureReport", "SnapshotReadbackError", "validate_snapshot_streams"]
