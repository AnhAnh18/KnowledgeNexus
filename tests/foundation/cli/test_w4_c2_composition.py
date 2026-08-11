from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import confluence_subtree_corpus as subtree
from knowledgenexus.foundation.cli import export_m10_snapshot as export_cli
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.delta_inventory import (
    CurrentSelectionPage,
    DeltaInventoryEntry,
    DeltaInventoryEnvelope,
    DeltaInventoryMetrics,
    DeltaInventoryState,
    DeltaInventoryScope,
    PriorConfluenceDocument,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotResult
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import (
    M10FullSnapshotExporter,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
from knowledgenexus.foundation.infrastructure.sidecars import DeltaInventoryArtifactStore
from knowledgenexus.foundation.infrastructure.exporters.delta_snapshot_reader import PublishedSnapshotReader
from knowledgenexus.foundation.domain.rules.dataset_version_generator import DatasetVersionGenerator
import knowledgenexus.foundation.infrastructure.confluence as confluence_infra
import knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport as retry_infra
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class _Adapter:
    def __init__(self, value):
        self.value = value
    def collect(self, request):
        return self.value


RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")


def test_run_routes_delta_and_full_to_their_real_exporter_classes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path)
    confluence, git = _handoffs()
    full_result = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(git)
    ).execute(request)
    delta_request = replace(request, export_mode="delta", base_dataset_version=full_result.dataset_version)
    seen: list[str] = []

    class DeltaSpy:
        def __init__(self, **kwargs):
            seen.append("delta")
        def execute(self, value):
            assert value is delta_request
            return full_result

    class FullSpy:
        def __init__(self, **kwargs):
            seen.append("full")
        def execute(self, value):
            assert value is request
            return full_result

    monkeypatch.setattr(export_cli, "M10DeltaSnapshotExporter", DeltaSpy)
    monkeypatch.setattr(export_cli, "M10FullSnapshotExporter", FullSpy)
    assert export_cli.run(
        request=delta_request,
        confluence_adapter=object(), git_adapter=object(),
        prior_snapshot_reader=object(), delta_inventory=(object(),),
    ) is full_result
    assert export_cli.run(request=request, confluence_adapter=object(), git_adapter=object()) is full_result
    assert seen == ["delta", "full"]


class _FakeTransport:
    request_profile_version = "m7-confluence-request-profile-v1"
    checkpoint_bound = True

    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self):
        return type("Snapshot", (), {"requests_started_for_run": self.calls})()

    def get_response_bytes(self, *, path: str, query: dict[str, str]):
        self.calls += 1
        return type("Response", (), {"status_code": 404, "body": b"gone"})()


class _FakeSession:
    def __init__(self, transport: _FakeTransport) -> None:
        self.transport = transport
        self.completed = False

    def complete_session(self) -> None:
        self.completed = True


class _FakeCheckpoint:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    @contextmanager
    def activate_raw_generation(self, request):
        yield self.session


class _FakeComposition:
    def __init__(self, session: _FakeSession) -> None:
        self.checkpoint_run_port = _FakeCheckpoint(session)
        self.http_inner = object()
        self.retry_profile = object()


def test_capture_delta_inventory_phase_writes_raw_then_derived_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    request = _request(dataset)
    confluence, git = _handoffs()
    full = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(git)
    ).execute(request)
    state = tmp_path / "state"
    raw = tmp_path / "raw"
    state.mkdir()
    raw.mkdir()
    rows = [{"page_id": "999", "crawled_at": "2026-08-05T00:00:00Z", "expected_source_version": "1"}]
    selection = {
        "format_version": "confluence-subtree-selection-v1",
        "run_id": str(RUN), "generation_id": str(RUN),
        "selection_identity": subtree._selection_identity(rows), "items": rows,
    }
    run_dir = state / "runs" / str(RUN)
    run_dir.mkdir(parents=True)
    (run_dir / "inventory-selection.json").write_text(json.dumps(selection), encoding="utf-8")
    transport = _FakeTransport()
    session = _FakeSession(transport)
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.test")
    monkeypatch.setattr(confluence_infra, "compose_live_subtree", lambda **kwargs: _FakeComposition(session))
    monkeypatch.setattr(retry_infra, "RetryingConfluenceHttpTransport", lambda **kwargs: transport)
    profile = Path("contracts/foundation/crawl_reliability_profile.yaml").resolve()
    argv = [
        "capture-delta-inventory", "--state-dir", str(state), "--max-pages", "10",
        "--batch-size", "1", "--raw-root", str(raw), "--run-id", str(RUN),
        "--reliability-profile-path", str(profile), "--space-key", "DOC",
        "--root-page-id", "999", "--dataset-root", str(request.dataset_root),
        "--base-dataset-version", full.dataset_version,
    ]
    result = subtree.main(argv)
    assert result == 0
    artifact = DeltaInventoryArtifactStore(state_root=state / "runs").read(generation_id=RUN)
    assert artifact.entries[0].detail == "confluence_404_may_mask_access_revoked"
    raw_path = ConfluenceRawPageGenerationStore(raw_root=raw).resolve_page_path(run_id=RUN, page_id="123")
    assert raw_path.is_file()
    assert (run_dir / "delta-inventory.json").is_file()
    assert session.completed is True
    assert transport.calls == 1
    assert subtree.main(argv) == 0
    assert transport.calls == 1


def test_full_mode_rejects_delta_only_flag_and_output_has_no_hash(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert export_cli.main(["--export-mode", "full_snapshot", "--exclude-ancestor-page-id", "1"]) == export_cli.EXIT_CONFIGURATION
    captured = capsys.readouterr()
    assert "hash" not in captured.err.lower()


def test_offline_export_socket_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("socket use")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    request = _request(tmp_path)
    confluence, git = _handoffs()
    result = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(git)
    ).execute(request)
    assert type(result) is M10SnapshotResult


def _empty_git(git):
    from knowledgenexus.foundation.domain.models.m10_composition import M10GitHandoff
    return M10GitHandoff(git.repository, git.branch, git.commit, (), (), (), (), (), (), ())


def _publish_delta_artifact(*, state: Path, request, base_streams, accepted_base: str) -> None:
    entries = []
    for row in base_streams["documents"]:
        if row.get("source_system") != "confluence":
            continue
        document_id = row["document_id"]
        entries.append(DeltaInventoryEntry(document_id, DeltaInventoryState.PRESENT))
    entries.sort(key=lambda item: item.document_id)
    metrics = DeltaInventoryMetrics(present_count=len(entries), source_deleted_count=0, access_revoked_count=0, moved_out_of_scope_count=0)
    from knowledgenexus.foundation.application.use_cases.capture_delta_inventory import selection_identity, scope_identity
    selection = selection_identity(tuple(CurrentSelectionPage(page_id) for page_id in request.ordered_page_ids))
    scope = scope_identity(DeltaInventoryScope(tuple(request.confluence_scope.root_page_ids), tuple(item.page_id for item in request.confluence_exclusions), ()))
    envelope = DeltaInventoryEnvelope("1.0.0", request.run_id, request.generation_id, selection, accepted_base, scope, tuple(entries), metrics)
    DeltaInventoryArtifactStore(state_root=state / "runs").publish(envelope=envelope)


def test_real_offline_delta_main_publishes_sparse_delta_and_reuses_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    base_request = _request(dataset)
    confluence, git = _handoffs()
    empty_git = _empty_git(git)
    base = M10FullSnapshotExporter(
        confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(empty_git)
    ).execute(base_request)
    delta_request = replace(base_request, generated_at="2026-08-05T00:01:00Z", export_mode="delta", base_dataset_version=base.dataset_version)
    base_read = PublishedSnapshotReader(dataset_root=dataset, validator=__import__("knowledgenexus.shared.contracts.foundation.schema_validator", fromlist=["FoundationSchemaValidator"]).FoundationSchemaValidator()).read(base.dataset_version)
    state = tmp_path / "state"
    (state / "runs").mkdir(parents=True)
    _publish_delta_artifact(state=state, request=delta_request, base_streams=base_read.streams, accepted_base=base.dataset_version)
    stored = DeltaInventoryArtifactStore(state_root=state / "runs").read(generation_id=RUN)
    assert stored.accepted_base_dataset_version == base.dataset_version
    from knowledgenexus.foundation.application.use_cases.capture_delta_inventory import selection_identity, scope_identity
    assert stored.current_selection_identity == selection_identity(tuple(CurrentSelectionPage(page_id) for page_id in delta_request.ordered_page_ids))
    assert stored.current_scope_identity == scope_identity(DeltaInventoryScope(tuple(delta_request.confluence_scope.root_page_ids), (), ()))
    monkeypatch.setattr(export_cli, "_build_operator_inputs", lambda parsed: (delta_request, _Adapter(confluence), _Adapter(empty_git)))
    forbidden = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert export_cli.main([
        "--export-mode", "delta", "--state-dir", str(state), "--run-id", str(RUN),
        "--generation-id", str(RUN), "--base-dataset-version", base.dataset_version,
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "digest" not in payload
    published_version = DatasetVersionGenerator.generate(instant=__import__("datetime").datetime.fromisoformat(delta_request.generated_at.replace("Z", "+00:00")))
    published = PublishedSnapshotReader(dataset_root=dataset, validator=__import__("knowledgenexus.shared.contracts.foundation.schema_validator", fromlist=["FoundationSchemaValidator"]).FoundationSchemaValidator()).read(published_version)
    assert published.manifest["export_mode"] == "delta"
    assert published.manifest["base_dataset_version"] == base.dataset_version


def test_real_delta_main_rejects_inventory_base_mismatch_without_publication(tmp_path: Path, monkeypatch, capsys) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    base_request = _request(dataset)
    confluence, git = _handoffs()
    empty_git = _empty_git(git)
    base = M10FullSnapshotExporter(confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(empty_git)).execute(base_request)
    delta_request = replace(base_request, generated_at="2026-08-05T00:01:00Z", export_mode="delta", base_dataset_version=base.dataset_version)
    validator = __import__("knowledgenexus.shared.contracts.foundation.schema_validator", fromlist=["FoundationSchemaValidator"]).FoundationSchemaValidator()
    base_read = PublishedSnapshotReader(dataset_root=dataset, validator=validator).read(base.dataset_version)
    state = tmp_path / "state"
    (state / "runs").mkdir(parents=True)
    _publish_delta_artifact(state=state, request=delta_request, base_streams=base_read.streams, accepted_base="v20260806-000000-000000Z")
    monkeypatch.setattr(export_cli, "_build_operator_inputs", lambda parsed: (delta_request, _Adapter(confluence), _Adapter(empty_git)))
    assert export_cli.main(["--export-mode", "delta", "--state-dir", str(state), "--run-id", str(RUN), "--generation-id", str(RUN), "--base-dataset-version", base.dataset_version]) == export_cli.EXIT_CONFIGURATION
    assert json.loads(capsys.readouterr().err)["category"] == "configuration"
    assert (dataset / base.dataset_version).is_dir()
