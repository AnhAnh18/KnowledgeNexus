from __future__ import annotations

import copy
from dataclasses import dataclass

from knowledgenexus.foundation.domain.records.sync_state_record_builder import (
    SyncStateRecordBuilder,
)


class SyncStateSnapshotError(Exception):
    """Sanitized failure for the pure sync-state snapshot projection."""


@dataclass(frozen=True)
class SyncStateSnapshotResult:
    records: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(type(record) is not dict for record in self.records):
            raise TypeError("sync state records are invalid")
        copied = tuple(copy.deepcopy(record) for record in self.records)
        ids = tuple(record.get("entity_id") for record in copied)
        if any(type(entity_id) is not str or not entity_id for entity_id in ids):
            raise ValueError("sync state entity IDs are invalid")
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("sync state ordering or identity is invalid")
        object.__setattr__(self, "records", copied)


class BuildSyncStateSnapshot:
    """Project emitted documents/media into exported sync-state rows."""

    def execute(
        self,
        *,
        source_id: object,
        synced_at: object,
        documents: object,
        media_assets: object = (),
        repository_id: object | None = None,
        repository_version: object | None = None,
        inventory: object | None = None,
    ) -> SyncStateSnapshotResult:
        if type(source_id) is not str or not source_id or type(synced_at) is not str or not synced_at:
            raise SyncStateSnapshotError("invalid input")
        if type(documents) is not tuple or type(media_assets) is not tuple:
            raise SyncStateSnapshotError("invalid input")
        if repository_id is not None and (type(repository_id) is not str or not repository_id):
            raise SyncStateSnapshotError("invalid input")
        if repository_version is not None and (type(repository_version) is not str or not repository_version):
            raise SyncStateSnapshotError("invalid input")
        if inventory is not None:
            return self._from_inventory(
                source_id=source_id,
                synced_at=synced_at,
                documents=documents,
                media_assets=media_assets,
                repository_id=repository_id,
                inventory=inventory,
            )
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for document in documents:
            if type(document) is not dict:
                raise SyncStateSnapshotError("invalid document")
            entity_id = document.get("document_id")
            source_system = document.get("source_system")
            if type(entity_id) is not str or not entity_id:
                raise SyncStateSnapshotError("invalid document identity")
            if source_system == "confluence":
                entity_type = "page"
            elif source_system == "git":
                entity_type = "file"
            else:
                raise SyncStateSnapshotError("invalid document source")
            rows.append(
                SyncStateRecordBuilder.build(
                    source_id=source_id,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    last_seen_version=document.get("source_version"),
                    last_content_hash=document.get("content_hash"),
                    last_synced_at=synced_at,
                )
            )
            if entity_id in seen:
                raise SyncStateSnapshotError("duplicate entity")
            seen.add(entity_id)
        for media in media_assets:
            if type(media) is not dict:
                raise SyncStateSnapshotError("invalid media")
            entity_id = media.get("media_id")
            if type(entity_id) is not str or not entity_id or media.get("source_system") != "confluence":
                raise SyncStateSnapshotError("invalid media identity")
            rows.append(
                SyncStateRecordBuilder.build(
                    source_id=source_id,
                    entity_id=entity_id,
                    entity_type="attachment",
                    last_seen_version=media.get("source_version"),
                    last_content_hash=media.get("content_hash"),
                    last_synced_at=synced_at,
                )
            )
            if entity_id in seen:
                raise SyncStateSnapshotError("duplicate entity")
            seen.add(entity_id)
        if repository_id is not None:
            if repository_id in seen:
                raise SyncStateSnapshotError("duplicate repository entity")
            rows.append(
                SyncStateRecordBuilder.build(
                    source_id=source_id,
                    entity_id=repository_id,
                    entity_type="repo",
                    last_seen_version=repository_version,
                    last_content_hash=None,
                    last_synced_at=synced_at,
                )
            )
        rows.sort(key=lambda record: str(record["entity_id"]))
        return SyncStateSnapshotResult(records=tuple(rows))

    @staticmethod
    def _from_inventory(
        *,
        source_id: str,
        synced_at: str,
        documents: tuple[dict[str, object], ...],
        media_assets: tuple[dict[str, object], ...],
        repository_id: str | None,
        inventory: object,
    ) -> SyncStateSnapshotResult:
        if type(inventory) is not tuple or any(type(row) is not dict for row in inventory):
            raise SyncStateSnapshotError("invalid authoritative inventory")
        expected: set[str] = {
            str(row.get("document_id")) for row in documents
        } | {str(row.get("media_id")) for row in media_assets}
        if repository_id is not None:
            expected.add(repository_id)
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        allowed = {
            "source_id", "entity_id", "entity_type", "last_seen_version",
            "last_content_hash", "last_synced_at", "status",
        }
        for row in inventory:
            if set(row) != allowed:
                raise SyncStateSnapshotError("authoritative inventory fields are invalid")
            if row.get("source_id") != source_id or row.get("last_synced_at") != synced_at:
                raise SyncStateSnapshotError("authoritative inventory provenance is invalid")
            entity_id = row.get("entity_id")
            if type(entity_id) is not str or entity_id in seen or entity_id not in expected:
                raise SyncStateSnapshotError("authoritative inventory identity is invalid")
            seen.add(entity_id)
            try:
                rows.append(SyncStateRecordBuilder.build(**row))
            except (TypeError, ValueError):
                raise SyncStateSnapshotError("authoritative inventory record is invalid") from None
        if seen != expected:
            raise SyncStateSnapshotError("authoritative inventory does not cover emitted entities")
        rows.sort(key=lambda record: str(record["entity_id"]))
        return SyncStateSnapshotResult(records=tuple(rows))


__all__ = ["BuildSyncStateSnapshot", "SyncStateSnapshotError", "SyncStateSnapshotResult"]
