from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.project_m10_delta import (
    M10DeltaOrchestrationError,
    M10DeltaOrchestrator,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotMetrics
from knowledgenexus.foundation.domain.models.delta_propagation import (
    DeltaInventoryEntry,
    DeltaInventoryState,
)
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import (
    M10DeltaSnapshotExporter,
    M10FullSnapshotExporter,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from tests.foundation.integration.test_m10_synthetic_acceptance import _Adapter
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


_BASE_VERSION = "v20260805-000000-000000Z"


class _PriorSnapshot:
    def __init__(self, projection: object) -> None:
        self.streams = {
            name: tuple(getattr(projection, name))
            for name in (
                "documents", "chunks", "relations", "acl", "media_assets",
                "symbols", "sync_state", "tombstones",
            )
        }
        self.manifest = {
            "dataset_version": _BASE_VERSION,
            "config_hash": projection.config_hash,
            "chunker_version": projection.chunker_version,
        }


def _composed(tmp_path: Path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    exporter = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(git),
    )
    return request, exporter._composer.execute(request).projection


def _orchestrator(projection: object) -> M10DeltaOrchestrator:
    prior = _PriorSnapshot(projection)
    return M10DeltaOrchestrator(
        prior_snapshot_reader=lambda version: prior,
        schema_validator=FoundationSchemaValidator(),
    )


def test_orchestrator_cascades_removed_document_dependents(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    git_documents = tuple(row for row in full.documents if row["source_system"] == "git")
    git_document_ids = {row["document_id"] for row in git_documents}
    current_chunks = tuple(row for row in full.chunks if row["document_id"] in git_document_ids)
    current_acl = tuple(row for row in full.acl if row["document_id"] in git_document_ids)
    current_symbols = tuple(row for row in full.symbols if row["repo"] == "org-repo")
    current_sync = tuple(
        row for row in full.sync_state
        if row["entity_id"] in git_document_ids or row["entity_id"] == "org-repo"
    )
    metrics = M10SnapshotMetrics(
        documents=len(git_documents),
        chunks=len(current_chunks),
        relations=0,
        acl=len(current_acl),
        media_assets=0,
        symbols=len(current_symbols),
        sync_state=len(current_sync),
        tombstones=0,
        confluence_documents=0,
        git_documents=len(git_documents),
        unresolved_relations=0,
        media_processed=0,
        media_failed=0,
        symbols_resolved=sum(row.get("chunk_id") is not None for row in current_symbols),
        default_deny_chunks=0,
    )
    current = replace(
        full,
        generated_at="2026-08-05T00:01:00Z",
        documents=git_documents,
        chunks=current_chunks,
        relations=(),
        acl=current_acl,
        media_assets=(),
        symbols=current_symbols,
        sync_state=current_sync,
        tombstones=(),
        metrics=metrics,
        export_mode="delta",
    )
    delta_request = replace(
        request,
        generated_at="2026-08-05T00:01:00Z",
        export_mode="delta",
        base_dataset_version=_BASE_VERSION,
    )

    with pytest.raises(M10DeltaOrchestrationError, match="non-Confluence document"):
        _orchestrator(full).execute(
            delta_request,
            current,
            inventory=(
                DeltaInventoryEntry(
                    "confluence:page:123",
                    DeltaInventoryState.ACCESS_REVOKED,
                    "1",
                ),
            ),
        )


def test_orchestrator_reemits_acl_and_chunks_without_content_tombstones(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    acl = []
    for row in full.acl:
        copied = dict(row)
        if copied["document_id"] == "confluence:page:123":
            copied["acl_tags"] = ["space:NEW"]
        acl.append(copied)
    chunks = []
    for row in full.chunks:
        copied = dict(row)
        if copied["document_id"] == "confluence:page:123":
            copied["acl_tags"] = ["space:NEW"]
        chunks.append(copied)
    current = replace(
        full,
        generated_at="2026-08-05T00:01:00Z",
        acl=tuple(acl),
        chunks=tuple(chunks),
        tombstones=(),
        metrics=replace(full.metrics, tombstones=0),
        export_mode="delta",
    )
    delta_request = replace(
        request,
        generated_at="2026-08-05T00:01:00Z",
        export_mode="delta",
        base_dataset_version=_BASE_VERSION,
    )

    with pytest.raises(M10DeltaOrchestrationError, match="non-Confluence document"):
        _orchestrator(full).execute(delta_request, current)


@pytest.mark.parametrize("bad_reader", [None, object()])
def test_orchestrator_rejects_invalid_reader_before_execution(bad_reader: object) -> None:
    with pytest.raises(TypeError):
        M10DeltaOrchestrator(
            prior_snapshot_reader=bad_reader,
            schema_validator=FoundationSchemaValidator(),
        )


def test_orchestrator_sanitizes_prior_read_failure(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    orchestrator = M10DeltaOrchestrator(
        prior_snapshot_reader=lambda version: (_ for _ in ()).throw(RuntimeError("private path")),
        schema_validator=FoundationSchemaValidator(),
    )
    delta_request = replace(
        request,
        export_mode="delta",
        base_dataset_version=_BASE_VERSION,
    )
    current = replace(full, export_mode="delta")

    with pytest.raises(M10DeltaOrchestrationError, match="prior snapshot read failed") as exc:
        orchestrator.execute(delta_request, current)
    assert "private" not in str(exc.value)


def test_delta_exporter_runs_orchestrator_before_delta_publication(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    confluence, git = _handoffs()
    full_export = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(git),
    ).execute(request)
    assert full_export.dataset_version == _BASE_VERSION

    prior = _PriorSnapshot(full)
    delta_request = replace(
        request,
        generated_at="2026-08-05T00:01:00Z",
        export_mode="delta",
        base_dataset_version=_BASE_VERSION,
    )
    inventory = (
        DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT, "1"),
    )
    exporter = M10DeltaSnapshotExporter(
        prior_snapshot_reader=lambda version: prior,
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(git),
        delta_inventory=inventory,
    )
    orchestrator = exporter._delta_orchestrator
    observed: dict[str, object] = {}
    original_execute = orchestrator.execute

    def recording_execute(request_value, projection_value, *, inventory=()):
        observed["inventory"] = inventory
        return original_execute(request_value, projection_value, inventory=inventory)

    orchestrator.execute = recording_execute
    with pytest.raises(Exception):
        exporter.execute(delta_request)
