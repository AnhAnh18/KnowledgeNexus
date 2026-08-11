from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.project_m10_delta import (
    M10DeltaOrchestrationError,
    M10DeltaOrchestrator,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotMetrics
from knowledgenexus.foundation.domain.models.m10_composition import M10GitHandoff
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
    empty_git = M10GitHandoff(git.repository, git.branch, git.commit, (), (), (), (), (), (), ())
    exporter = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(empty_git),
    )
    projection = exporter._composer.execute(request).projection
    # W4-B is intentionally Confluence-only; keep this forcing fixture free
    # of Git rows so success paths exercise sparse semantics rather than the
    # boundary rejection.
    document_ids = {row["document_id"] for row in projection.documents if row.get("source_system") == "confluence"}
    streams = {
        "documents": tuple(row for row in projection.documents if row.get("document_id") in document_ids),
        "chunks": tuple(row for row in projection.chunks if row.get("document_id") in document_ids),
        "relations": tuple(row for row in projection.relations if row.get("source_id") in document_ids),
        "acl": tuple(row for row in projection.acl if row.get("document_id") in document_ids),
        "media_assets": tuple(row for row in projection.media_assets if row.get("parent_document_id") in document_ids),
        "symbols": tuple(row for row in projection.symbols if row.get("document_id") in document_ids),
        "sync_state": tuple(row for row in projection.sync_state if row.get("entity_id") in document_ids),
        "tombstones": (),
    }
    counts = {name: len(rows) for name, rows in streams.items()}
    metrics = replace(
        projection.metrics,
        documents=counts["documents"], chunks=counts["chunks"], relations=counts["relations"],
        acl=counts["acl"], media_assets=counts["media_assets"], symbols=counts["symbols"],
        sync_state=counts["sync_state"], tombstones=0,
        confluence_documents=counts["documents"], git_documents=0,
        unresolved_relations=sum(row.get("resolution_status") != "resolved" for row in streams["relations"]),
        media_processed=sum(row.get("processing_status") in {"parsed", "ocr", "summarized"} for row in streams["media_assets"]),
        media_failed=sum(row.get("processing_status") == "failed" for row in streams["media_assets"]),
        symbols_resolved=sum(row.get("chunk_id") is not None for row in streams["symbols"]),
        default_deny_chunks=sum(row.get("acl_tags") == ["restricted:unresolved"] for row in streams["chunks"]),
    )
    return request, replace(projection, **streams, metrics=metrics)


def _orchestrator(projection: object) -> M10DeltaOrchestrator:
    prior = _PriorSnapshot(projection)
    return M10DeltaOrchestrator(
        prior_snapshot_reader=lambda version: prior,
        schema_validator=FoundationSchemaValidator(),
    )


def test_orchestrator_cascades_removed_document_dependents(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    document_id = "confluence:page:123"
    current_chunks = ()
    current_acl = ()
    current_symbols = ()
    current_sync = ()
    metrics = M10SnapshotMetrics(
        documents=0,
        chunks=len(current_chunks),
        relations=0,
        acl=len(current_acl),
        media_assets=0,
        symbols=len(current_symbols),
        sync_state=len(current_sync),
        tombstones=0,
        confluence_documents=0,
        git_documents=0,
        unresolved_relations=0,
        media_processed=0,
        media_failed=0,
        symbols_resolved=sum(row.get("chunk_id") is not None for row in current_symbols),
        default_deny_chunks=0,
    )
    current = replace(
        full,
        generated_at="2026-08-05T00:01:00Z",
        documents=(),
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

    result = _orchestrator(full).execute(delta_request, current, inventory=(
        DeltaInventoryEntry(document_id, DeltaInventoryState.SOURCE_DELETED, "1", "confluence_404_may_mask_access_revoked"),
    ))
    emitted = result.projection
    assert emitted.documents == () and emitted.chunks == () and emitted.acl == ()
    assert emitted.tombstones
    document_tombstone = next(row for row in emitted.tombstones if row.get("entity_id") == document_id)
    assert document_tombstone.get("detail") == "confluence_404_may_mask_access_revoked"


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

    result = _orchestrator(full).execute(
        delta_request,
        current,
        inventory=(DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT),),
    )
    assert any(row["document_id"] == "confluence:page:123" for row in result.projection.chunks)
    assert any(row["document_id"] == "confluence:page:123" for row in result.projection.acl)
    assert result.projection.documents == ()
    assert not any(row.get("reason") == "content_changed" for row in result.projection.tombstones)


def test_unchanged_second_sync_emits_valid_empty_delta(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    delta_request = replace(request, generated_at="2026-08-05T00:01:00Z", export_mode="delta", base_dataset_version=_BASE_VERSION)
    result = _orchestrator(full).execute(
        delta_request,
        replace(full, generated_at="2026-08-05T00:01:00Z", export_mode="delta", tombstones=(), metrics=replace(full.metrics, tombstones=0)),
        inventory=(DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT),),
    )
    projection = result.projection
    assert all(not getattr(projection, name) for name in ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones"))


def test_byte_changed_document_is_emitted_even_when_content_hash_is_unchanged(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    documents = []
    for row in full.documents:
        copied = dict(row)
        if copied["document_id"] == "confluence:page:123":
            copied["title"] = copied["title"] + " (renamed)"
        documents.append(copied)
    current = replace(
        full,
        generated_at="2026-08-05T00:01:00Z",
        documents=tuple(documents),
        tombstones=(),
        metrics=replace(full.metrics, tombstones=0),
        export_mode="delta",
    )
    delta_request = replace(request, generated_at="2026-08-05T00:01:00Z", export_mode="delta", base_dataset_version=_BASE_VERSION)
    result = _orchestrator(full).execute(
        delta_request,
        current,
        inventory=(DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT),),
    )
    assert [row["document_id"] for row in result.projection.documents] == ["confluence:page:123"]


def test_config_invalidation_reemits_tombstoned_replacements(tmp_path: Path) -> None:
    request, full = _composed(tmp_path)
    delta_request = replace(request, generated_at="2026-08-05T00:01:00Z", export_mode="delta", base_dataset_version=_BASE_VERSION)
    current = replace(full, generated_at="2026-08-05T00:01:00Z", config_hash="f" * 64, export_mode="delta", tombstones=(), metrics=replace(full.metrics, tombstones=0))
    result = _orchestrator(full).execute(
        delta_request,
        current,
        inventory=(DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT),),
    )
    projection = result.projection
    assert projection.tombstones
    assert projection.documents or projection.chunks or projection.acl or projection.relations or projection.sync_state


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
    empty_git = M10GitHandoff(git.repository, git.branch, git.commit, (), (), (), (), (), (), ())
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
        DeltaInventoryEntry("confluence:page:123", DeltaInventoryState.PRESENT),
    )
    exporter = M10DeltaSnapshotExporter(
        prior_snapshot_reader=lambda version: prior,
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(empty_git),
        delta_inventory=inventory,
    )
    orchestrator = exporter._delta_orchestrator
    observed: dict[str, object] = {}
    original_execute = orchestrator.execute

    def recording_execute(request_value, projection_value, *, inventory=()):
        observed["inventory"] = inventory
        return original_execute(request_value, projection_value, inventory=inventory)

    orchestrator.execute = recording_execute
    result = exporter.execute(delta_request)
    assert result.status == "published"
    assert observed["inventory"] == inventory
    assert result.metrics is not None
