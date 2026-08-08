from __future__ import annotations

import copy

from knowledgenexus.foundation.application.use_cases.build_sync_state_snapshot import (
    BuildSyncStateSnapshot,
    SyncStateSnapshotError,
)
from knowledgenexus.foundation.domain.models.m10_composition import (
    M10ConfluenceHandoff,
    M10GitHandoff,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotRequest


class M10HandoffAssemblyError(Exception):
    """Sanitized failure for trusted M10 handoff assembly."""


def _records(value: object, field_name: str) -> tuple[dict[str, object], ...]:
    if type(value) is not tuple or any(type(record) is not dict for record in value):
        raise M10HandoffAssemblyError(f"invalid {field_name}")
    return tuple(copy.deepcopy(record) for record in value)


class AssembleConfluenceM10Handoff:
    """Assemble a Confluence handoff from already-materialized Foundation streams."""

    def execute(
        self,
        *,
        request: object,
        source_version: object,
        raw_artifact_identity: object,
        documents: object,
        chunks: object,
        relations: object,
        acl: object,
        media_assets: object = (),
        tombstones: object = (),
    ) -> M10ConfluenceHandoff:
        if type(request) is not M10SnapshotRequest:
            raise M10HandoffAssemblyError("invalid request")
        if type(source_version) is not str or not source_version or type(raw_artifact_identity) is not str or not raw_artifact_identity:
            raise M10HandoffAssemblyError("invalid provenance")
        docs = _records(documents, "documents")
        chunks_rows = _records(chunks, "chunks")
        relation_rows = _records(relations, "relations")
        acl_rows = _records(acl, "acl")
        media_rows = _records(media_assets, "media_assets")
        tombstone_rows = _records(tombstones, "tombstones")
        try:
            sync = BuildSyncStateSnapshot().execute(
                source_id=request.confluence_scope.source_id,
                synced_at=request.generated_at,
                documents=docs,
                media_assets=media_rows,
            )
        except (SyncStateSnapshotError, TypeError, ValueError):
            raise M10HandoffAssemblyError("sync state assembly failed") from None
        try:
            return M10ConfluenceHandoff(
                request.run_id,
                request.generation_id,
                source_version,
                docs,
                chunks_rows,
                relation_rows,
                acl_rows,
                media_rows,
                (),
                sync.records,
                raw_artifact_identity,
                (),
                tombstone_rows,
            )
        except (TypeError, ValueError):
            raise M10HandoffAssemblyError("Confluence handoff is invalid") from None


class AssembleGitM10Handoff:
    """Assemble a Git handoff and derive its file/repository sync rows."""

    def execute(
        self,
        *,
        request: object,
        documents: object,
        chunks: object,
        acl: object,
        symbols: object = (),
        tombstones: object = (),
    ) -> M10GitHandoff:
        if type(request) is not M10SnapshotRequest:
            raise M10HandoffAssemblyError("invalid request")
        docs = _records(documents, "documents")
        chunks_rows = _records(chunks, "chunks")
        acl_rows = _records(acl, "acl")
        symbol_rows = _records(symbols, "symbols")
        tombstone_rows = _records(tombstones, "tombstones")
        try:
            sync = BuildSyncStateSnapshot().execute(
                source_id=request.git_repository,
                synced_at=request.generated_at,
                documents=docs,
                repository_id=request.git_repository,
                repository_version=request.git_commit,
            )
            return M10GitHandoff(
                request.git_repository,
                request.git_branch,
                request.git_commit,
                docs,
                chunks_rows,
                (),
                acl_rows,
                (),
                symbol_rows,
                sync.records,
                (),
                tombstone_rows,
            )
        except (SyncStateSnapshotError, TypeError, ValueError):
            raise M10HandoffAssemblyError("Git handoff assembly failed") from None


__all__ = [
    "AssembleConfluenceM10Handoff",
    "AssembleGitM10Handoff",
    "M10HandoffAssemblyError",
]
