import argparse
import hashlib
import json
from pathlib import Path

import pytest

import knowledgenexus.foundation.infrastructure.confluence as confluence_pkg
import knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_adapter as page_adapter_module
import knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport as retry_transport_module
import knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_orphan_inspector as orphan_inspector_module
import knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages as capture_pages_module
from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import (
    PageCaptureResult,
)
from knowledgenexus.foundation.cli import confluence_subtree_corpus as cli
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CanonicalIncludeRoots,
    CrawlRunSnapshot,
    CrawlRunStatus,
    CrawlRunId,
    IncludeRootProgress,
    InventoryPhaseStatus,
    InventoryRootCommit,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    ConfluenceCrawlFingerprint,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_inventory_window import ConfluenceInventoryWindow
from knowledgenexus.foundation.domain.models.confluence_page_content import NormalizationReferenceIntent
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetResult,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaBodyStoreBudget,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store import (
    ConfluenceRawAttachmentStore,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    ActivateRawGenerationRequest,
    CheckpointRunInventoryComplete,
    CheckpointRunSelectionFailure,
    CheckpointRunSelectionFailureCategory,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
APPROVED_PROFILE_PATH = REPO_ROOT / "contracts" / "foundation" / "crawl_reliability_profile.yaml"


main = cli.main


RUN_ID = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")


def _selection():
    rows = [{
        "page_id": "1000",
        "crawled_at": "2026-08-10T00:00:00Z",
        "expected_source_version": "7",
    }]
    return {
        "format_version": "confluence-subtree-selection-v1",
        "run_id": str(RUN_ID),
        "generation_id": str(RUN_ID),
        "selection_identity": cli._selection_identity(rows),
        "items": rows,
    }


def _result(*, drawio: bool):
    intents = (
        NormalizationReferenceIntent(
            1, "drawio", "deferred_mvp", "diagram.drawio", "diagram.drawio"
        ),
    ) if drawio else ()
    return ConfluencePageSetResult(
        documents=({
            "document_id": "confluence:page:1000",
            "page_id": "1000",
            "source_version": "7",
        },),
        chunks=({"chunk_id": "chunk-1"},),
        page_metrics=(ConfluencePageSetPageMetrics(
            1, 1, 0, len(intents), (("paragraph", 1),)
        ),),
        metrics=ConfluencePageSetMetrics(
            1, 1, 0, 1, 1, 0, len(intents), (("paragraph", 1),)
        ),
        reference_intents_by_page=(("confluence:page:1000", intents),),
    )


def _args(**overrides):
    values = {
        "run_id": str(RUN_ID), "selection_path": None, "max_pages": 10,
        "raw_root": "unused", "chunking_profile_path": "unused",
        "tokenizer_assets_dir": "unused", "output_dir": None,
        "reliability_profile_path": "unused", "batch_size": 100,
        "space_key": "SPACE", "root_page_id": "1000",
        "resume_run_id": None, "resume_unique": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_help_exits_zero_without_failure_payload(capsys):
    assert main(["--help"]) == 0
    assert '"status":"failed"' not in capsys.readouterr().out


def test_capture_pages_parser_accepts_only_positive_controlled_batch_stop() -> None:
    parsed = cli._parser().parse_args([
        "capture-pages", "--state-dir", "C:/state", "--max-pages", "5000",
        "--stop-after-batches", "2",
    ])
    assert parsed.stop_after_batches == 2
    with pytest.raises(SystemExit):
        cli._parser().parse_args([
            "capture-pages", "--state-dir", "C:/state", "--max-pages", "5000",
            "--stop-after-batches", "0",
        ])
    with pytest.raises(SystemExit):
        cli._parser().parse_args([
            "inventory", "--state-dir", "C:/state", "--max-pages", "5000",
            "--stop-after-batches", "2",
        ])


def test_capture_pages_main_forwards_controlled_batch_stop(monkeypatch, tmp_path, capsys) -> None:
    observed = {}

    def capture(args, state):
        observed["stop_after_batches"] = args.stop_after_batches
        observed["state"] = state
        return {"status": "stopped", "phase": "capture-pages"}

    monkeypatch.setattr(cli, "_capture_pages_phase", capture)
    state = tmp_path.resolve()
    assert main([
        "capture-pages", "--state-dir", str(state), "--max-pages", "5000",
        "--stop-after-batches", "2",
    ]) == 0
    assert observed == {"stop_after_batches": 2, "state": state}
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"


def test_capture_result_payload_exposes_only_aggregate_failure_categories() -> None:
    captured = PageCaptureResult(
        94,
        0,
        0,
        6,
        True,
        100,
        (("fetch_http", 4), ("fetch_response_size_limit", 2)),
    )

    assert cli._capture_pages_result_payload(captured) == {
        "status": "stopped",
        "phase": "capture-pages",
        "captured": 94,
        "replayed": 0,
        "skipped": 0,
        "failed": 6,
        "failure_categories": {
            "fetch_http": 4,
            "fetch_response_size_limit": 2,
        },
    }


@pytest.mark.parametrize("malformed", [None, object(), {}, []])
def test_capture_result_payload_rejects_wrong_runtime_types(malformed) -> None:
    with pytest.raises(TypeError, match="capture result"):
        cli._capture_pages_result_payload(malformed)


def test_drawio_phase_fails_closed_without_production_adapters(capsys, tmp_path):
    result = main(["capture-drawio", "--state-dir", str(tmp_path), "--max-pages", "5000"])
    assert result == 2
    assert capsys.readouterr().out == '{"status":"failed","error":"configuration"}\n'


def test_processing_state_uses_parent_page_version_and_real_result_tuple(monkeypatch, tmp_path):
    state = tmp_path.resolve()
    selection = _selection()
    cli._atomic_json(cli._state_path(state, str(RUN_ID), "inventory-selection.json"), selection)
    monkeypatch.setattr(cli, "_compose_page_processor", lambda *_args, **_kwargs: _result(drawio=True))

    outcome = cli._process_pages_phase(_args(), state)
    recorded = cli._read_json(cli._state_path(state, str(RUN_ID), "processing-state.json"))

    assert outcome["status"] == "complete"
    assert recorded["drawio_references"] == [{
        "parent_page_id": "1000",
        "filename": "diagram.drawio",
        "parent_source_version": "7",
    }]


def test_export_consumes_tuple_result_and_publishes_no_drawio_packet(monkeypatch, tmp_path):
    state = (tmp_path / "state").resolve()
    output = (tmp_path / "packet").resolve()
    selection = _selection()
    cli._atomic_json(cli._state_path(state, str(RUN_ID), "inventory-selection.json"), selection)
    result = _result(drawio=False)
    cli._atomic_json(
        cli._state_path(state, str(RUN_ID), "processing-state.json"),
        cli._processing_payload(run_id=RUN_ID, selection=selection, result=result),
    )
    monkeypatch.setattr(cli, "_compose_page_processor", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(cli, "_raw_page_bytes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_load_reliability_profile", lambda _value: {
        "inventory_page_size": 50, "max_pages_per_run": 5000,
        "max_total_requests_per_run": 50000, "max_attempts": 4,
        "max_response_bytes_per_request": 8388608,
        "max_raw_bytes_per_run": 34359738368,
        "max_raw_artifacts_per_run": 250000,
        "minimum_free_disk_reserve_bytes": 8589934592,
    })

    class Exporter:
        def __init__(self, *, validator):
            assert validator is not None

        def publish(self, **kwargs):
            assert kwargs["media_assets"] == []
            return {
                "format_version": "confluence-subtree-indexing-packet-v1",
                "document_count": 1,
                "chunk_count": 1,
                "media_asset_count": 0,
            }

    monkeypatch.setattr(cli, "SubtreePacketExporter", Exporter)
    outcome = cli._export_phase(_args(output_dir=str(output)), state)
    assert outcome["packet_published"] is True


def _drawio_state(*, media_asset: dict[str, object], selection: dict[str, object]) -> dict[str, object]:
    """One resolved draw.io reference on page 1000, bound the way
    `validate_drawio_capture_state` requires: `media_asset["parent_document_id"]`
    must equal `DocumentIdGenerator.confluence_page_id(parent_page_id)`, and
    `media_asset["filename"]` must equal the reference's filename.
    """
    reference = ["1000", "diagram.drawio", "7"]
    return {
        "format_version": "confluence-subtree-drawio-state-v1",
        "run_id": str(RUN_ID),
        "generation_id": str(RUN_ID),
        "selection_identity": selection["selection_identity"],
        "observed": [reference],
        "resolutions": [{
            "reference": reference, "media_id": media_asset["media_id"],
            "body_byte_count": media_asset["size_bytes"],
        }],
        "failed": 0,
        "downloaded_bytes": media_asset["size_bytes"],
        "artifact_count": 1,
        "media_assets": [media_asset],
    }


def _media_asset(*, media_id: str = "confluence:attachment:att1", processing_status: str = "parsed", extracted_text: str | None = "Node A -> Node B") -> dict[str, object]:
    return {
        "schema_version": "1.0", "media_id": media_id,
        "parent_document_id": "confluence:page:1000", "source_system": "confluence",
        "filename": "diagram.drawio", "mime_type": "application/vnd.jgraph.mxfile",
        "size_bytes": 42, "download_status": "downloaded",
        "processing_status": processing_status, "relevance": "high",
        "extracted_text": extracted_text, "summary": None, "confidence": None,
        "raw_uri": f"raw://confluence/attachments/{media_id}/deadbeef",
        "content_hash": "deadbeef", "source_version": "7",
        "updated_at": "2026-08-10T00:00:00Z", "crawled_at": "2026-08-10T00:00:00Z",
    }


class _FakeDiagramChunker:
    """Stands in for the real BuildConfluenceChunks so this test proves the
    _export_phase <-> _diagram_chunk_records wiring (right parent document
    looked up, result folded into the published chunk list) without loading a
    real chunking profile or tokenizer -- that token-level behaviour is
    already covered by test_build_confluence_chunks.py."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def execute_media_diagram(self, *, canonical_document, media_asset):
        self.calls.append((canonical_document["document_id"], media_asset["media_id"]))
        return type("Result", (), {
            "records": [{
                "chunk_id": f"diagram-chunk-{media_asset['media_id']}",
                "content_kind": "diagram",
                "document_id": canonical_document["document_id"],
            }]
        })()


def _export_with_drawio_state(monkeypatch, tmp_path, *, media_asset: dict[str, object], fake_chunker: _FakeDiagramChunker):
    state = (tmp_path / "state").resolve()
    output = (tmp_path / "packet").resolve()
    selection = _selection()
    cli._atomic_json(cli._state_path(state, str(RUN_ID), "inventory-selection.json"), selection)
    result = _result(drawio=True)
    cli._atomic_json(
        cli._state_path(state, str(RUN_ID), "processing-state.json"),
        cli._processing_payload(run_id=RUN_ID, selection=selection, result=result),
    )
    cli._atomic_json(
        cli._state_path(state, str(RUN_ID), "drawio-state.json"),
        _drawio_state(media_asset=media_asset, selection=selection),
    )
    monkeypatch.setattr(cli, "_compose_page_processor", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(cli, "_raw_page_bytes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_verify_drawio_media_assets_on_disk", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "_compose_diagram_chunker", lambda _args: fake_chunker)
    monkeypatch.setattr(cli, "_load_reliability_profile", lambda _value: {
        "inventory_page_size": 50, "max_pages_per_run": 5000,
        "max_total_requests_per_run": 50000, "max_attempts": 4,
        "max_response_bytes_per_request": 8388608,
        "max_raw_bytes_per_run": 34359738368,
        "max_raw_artifacts_per_run": 250000,
        "minimum_free_disk_reserve_bytes": 8589934592,
    })

    published: dict[str, object] = {}

    class Exporter:
        def __init__(self, *, validator):
            assert validator is not None

        def publish(self, **kwargs):
            published.update(kwargs)
            return {
                "format_version": "confluence-subtree-indexing-packet-v1",
                "document_count": len(kwargs["documents"]),
                "chunk_count": len(kwargs["chunks"]),
                "media_asset_count": len(kwargs["media_assets"]),
            }

    monkeypatch.setattr(cli, "SubtreePacketExporter", Exporter)
    monkeypatch.setattr(cli, "_export_mermaid_diagrams", lambda *_a, **_kw: 0)
    outcome = cli._export_phase(_args(output_dir=str(output)), state)
    return outcome, published


def test_export_folds_parsed_diagram_chunks_into_the_published_packet(monkeypatch, tmp_path):
    fake_chunker = _FakeDiagramChunker()
    outcome, published = _export_with_drawio_state(
        monkeypatch, tmp_path, media_asset=_media_asset(), fake_chunker=fake_chunker,
    )

    assert outcome["packet_published"] is True
    assert outcome["chunk_count"] == 2
    assert outcome["mermaid_diagrams_exported"] == 0
    # The chunker was called against the right parent page, not just any page.
    assert fake_chunker.calls == [("confluence:page:1000", "confluence:attachment:att1")]
    # Original page chunk plus the diagram chunk, both present -- nothing lost.
    chunk_ids = [chunk["chunk_id"] for chunk in published["chunks"]]
    assert chunk_ids == ["chunk-1", "diagram-chunk-confluence:attachment:att1"]
    diagram_chunk = published["chunks"][1]
    assert diagram_chunk["content_kind"] == "diagram"
    assert diagram_chunk["document_id"] == "confluence:page:1000"


@pytest.mark.parametrize(
    "media_asset",
    (
        _media_asset(processing_status="download_failed", extracted_text=None),
        _media_asset(processing_status="parsed", extracted_text=None),
        _media_asset(processing_status="parsed", extracted_text=""),
    ),
)
def test_export_skips_diagram_assets_that_are_not_successfully_parsed(monkeypatch, tmp_path, media_asset):
    fake_chunker = _FakeDiagramChunker()
    outcome, published = _export_with_drawio_state(
        monkeypatch, tmp_path, media_asset=media_asset, fake_chunker=fake_chunker,
    )

    assert outcome["packet_published"] is True
    assert outcome["chunk_count"] == 1
    # No qualifying asset -> the chunker (which would load a real tokenizer in
    # production) must never even be constructed, let alone called.
    assert fake_chunker.calls == []
    assert [chunk["chunk_id"] for chunk in published["chunks"]] == ["chunk-1"]


def test_export_mermaid_diagrams_writes_mmd_from_raw_xml(monkeypatch, tmp_path):
    """_export_mermaid_diagrams reads raw XML from disk, converts it to
    Mermaid, and writes .mmd files alongside the packet."""
    import knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store as store_mod
    import knowledgenexus.foundation.infrastructure.processors.drawio_mermaid_converter as conv_mod

    xml_body = (
        b'<mxfile><diagram id="d1"><mxGraphModel><root>'
        b'<mxCell id="0" /><mxCell id="1" parent="0" />'
        b'<mxCell id="A" value="Start" parent="1" vertex="1" />'
        b'<mxCell id="B" value="End" parent="1" vertex="1" />'
        b'<mxCell id="E" value="go" parent="1" edge="1" source="A" target="B" />'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    content_hash = hashlib.sha256(xml_body).hexdigest()
    output_dir = (tmp_path / "packet").resolve()
    output_dir.mkdir()
    asset = _media_asset()
    asset["raw_uri"] = f"raw://confluence/attachments/att1/{content_hash}"
    asset["content_hash"] = content_hash

    class _FakeEnvelope:
        body_bytes = xml_body

    class _FakeStore:
        def __init__(self, **_kw):
            pass
        def read_attachment(self, **_kw):
            return _FakeEnvelope()

    monkeypatch.setattr(store_mod, "ConfluenceRawAttachmentStore", _FakeStore)
    monkeypatch.setattr(cli, "_load_reliability_profile", lambda _v: {
        "inventory_page_size": 50,
        "max_pages_per_run": 5000,
        "max_total_requests_per_run": 50000,
        "max_attempts": 4,
        "max_response_bytes_per_request": 8388608,
        "max_raw_bytes_per_run": 34359738368,
        "max_raw_artifacts_per_run": 250000,
        "minimum_free_disk_reserve_bytes": 8589934592,
    })

    count = cli._export_mermaid_diagrams(
        _args(), output_dir=output_dir, media_assets=[asset],
    )

    assert count == 1
    mmd_files = list((output_dir / "diagrams").glob("*.mmd"))
    assert len(mmd_files) == 1
    content = mmd_files[0].read_text(encoding="utf-8")
    assert "flowchart TD" in content
    assert 'A["Start"]' in content
    assert 'B["End"]' in content
    assert '-->|"go"|' in content


def test_export_mermaid_diagrams_skips_unparsed_assets(tmp_path):
    output_dir = (tmp_path / "packet").resolve()
    output_dir.mkdir()
    asset = _media_asset(processing_status="download_failed", extracted_text=None)

    count = cli._export_mermaid_diagrams(
        _args(), output_dir=output_dir, media_assets=[asset],
    )

    assert count == 0
    assert not (output_dir / "diagrams").exists()


@pytest.mark.parametrize("media_assets", (None, object(), "not-assets", [object()]))
def test_export_mermaid_diagrams_rejects_wrong_runtime_types_before_output(tmp_path, media_assets):
    output_dir = (tmp_path / "packet").resolve()
    output_dir.mkdir()

    with pytest.raises((TypeError, ValueError)):
        cli._export_mermaid_diagrams(
            _args(), output_dir=output_dir, media_assets=media_assets,
        )

    assert not (output_dir / "diagrams").exists()


def test_export_mermaid_diagrams_skips_mismatched_raw_uri_hash(tmp_path):
    output_dir = (tmp_path / "packet").resolve()
    output_dir.mkdir()
    asset = _media_asset()
    asset["raw_uri"] = "raw://confluence/attachments/att1/" + "a" * 64
    asset["content_hash"] = "b" * 64

    count = cli._export_mermaid_diagrams(
        _args(), output_dir=output_dir, media_assets=[asset],
    )

    assert count == 0
    assert not (output_dir / "diagrams").exists()


def test_export_mermaid_diagrams_does_not_overwrite_duplicate_filenames(monkeypatch, tmp_path):
    import knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store as store_mod

    xml_body = (
        b'<mxfile><diagram id="d1"><mxGraphModel><root>'
        b'<mxCell id="0" /><mxCell id="1" parent="0" />'
        b'<mxCell id="A" value="Node" parent="1" vertex="1" />'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    content_hash = hashlib.sha256(xml_body).hexdigest()
    output_dir = (tmp_path / "packet").resolve()
    output_dir.mkdir()
    first = _media_asset(media_id="confluence:attachment:att1")
    second = _media_asset(media_id="confluence:attachment:att2")
    for attachment_id, asset in (("att1", first), ("att2", second)):
        asset["raw_uri"] = f"raw://confluence/attachments/{attachment_id}/{content_hash}"
        asset["content_hash"] = content_hash

    class _FakeEnvelope:
        body_bytes = xml_body

    class _FakeStore:
        def __init__(self, **_kwargs):
            pass

        def read_attachment(self, **_kwargs):
            return _FakeEnvelope()

    monkeypatch.setattr(store_mod, "ConfluenceRawAttachmentStore", _FakeStore)
    monkeypatch.setattr(cli, "_load_reliability_profile", lambda _value: {
        "inventory_page_size": 50,
        "max_pages_per_run": 5000,
        "max_total_requests_per_run": 50000,
        "max_attempts": 4,
        "max_response_bytes_per_request": 8388608,
        "max_raw_bytes_per_run": 34359738368,
        "max_raw_artifacts_per_run": 250000,
        "minimum_free_disk_reserve_bytes": 8589934592,
    })

    count = cli._export_mermaid_diagrams(
        _args(), output_dir=output_dir, media_assets=[first, second],
    )

    assert count == 2
    assert len(list((output_dir / "diagrams").glob("*.mmd"))) == 2


def test_zero_drawio_phase_persists_generation_bound_state_without_network(monkeypatch, tmp_path):
    state = tmp_path.resolve()
    selection = _selection()
    cli._atomic_json(cli._state_path(state, str(RUN_ID), "inventory-selection.json"), selection)
    cli._atomic_json(
        cli._state_path(state, str(RUN_ID), "processing-state.json"),
        cli._processing_payload(
            run_id=RUN_ID, selection=selection, result=_result(drawio=False)
        ),
    )
    monkeypatch.setattr(cli, "_load_reliability_profile", lambda _value: {
        "inventory_page_size": 50, "max_pages_per_run": 5000,
        "max_total_requests_per_run": 50000, "max_attempts": 4,
        "max_response_bytes_per_request": 8388608,
        "max_raw_bytes_per_run": 34359738368,
        "max_raw_artifacts_per_run": 250000,
        "minimum_free_disk_reserve_bytes": 8589934592,
    })
    monkeypatch.setattr(cli, "_raw_page_bytes", lambda *_args, **_kwargs: 100)

    outcome = cli._capture_drawio_phase(_args(), state)
    drawio = cli._read_json(cli._state_path(state, str(RUN_ID), "drawio-state.json"))

    assert outcome["status"] == "complete"
    assert drawio["run_id"] == str(RUN_ID)
    assert drawio["selection_identity"] == selection["selection_identity"]
    assert drawio["observed"] == []
    assert drawio["resolutions"] == []


def test_parser_keeps_reliability_and_chunking_profiles_distinct():
    parsed = cli._parser().parse_args([
        "process-pages", "--state-dir", "X", "--max-pages", "10",
        "--reliability-profile-path", "crawl.yaml",
        "--chunking-profile-path", "embedding.yaml",
    ])
    assert parsed.reliability_profile_path == "crawl.yaml"
    assert parsed.chunking_profile_path == "embedding.yaml"


def test_operator_page_cap_is_validated_without_mutating_the_reliability_profile():
    profile = {"max_pages_per_run": 10_000, "profile_id": "profile"}
    validated = cli._validated_page_bound(_args(max_pages=5_000), profile)
    assert validated["max_pages_per_run"] == 10_000
    assert validated is profile


def test_operator_page_cap_exceeding_the_profile_is_rejected():
    profile = {"max_pages_per_run": 10_000, "profile_id": "profile"}
    with pytest.raises(ValueError):
        cli._validated_page_bound(_args(max_pages=10_001), profile)


def test_validated_page_bound_output_still_satisfies_every_checkpoint_request():
    """Regression test: a real approved profile, once passed through
    ``_validated_page_bound``, must still be accepted by every checkpoint
    request type and by live composition's profile validation. Rewriting
    ``max_pages_per_run`` in place previously broke every live phase because
    the fingerprint/profile contract only accepts two closed, approved
    profiles (see ``_validate_profile``).
    """
    profile = cli._load_reliability_profile(str(APPROVED_PROFILE_PATH))
    args = _args(max_pages=10, space_key="SPACE", root_page_id="1000")
    validated = cli._validated_page_bound(args, profile)
    source_config = ConfluenceSourceConfig(
        source_id="confluence-root1",
        space_key="SPACE",
        include_roots=(ConfluenceIncludeRoot(page_id="1000"),),
        page_size=validated["inventory_page_size"],
    )
    common = dict(
        workspace=Path("C:/tmp/review-probe"),
        endpoint_url="https://example.invalid/wiki",
        source_config=source_config,
        reliability_profile=validated,
    )
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    StartNewRunRequest(**common)
    ResumeUniqueIncompleteRunRequest(**common)
    ResumeExplicitRunRequest(run_id=run_id, **common)
    ActivateRawGenerationRequest(run_id=run_id, **common)


def test_state_path_rejects_traversal_run_and_unknown_artifact(tmp_path):
    import pytest
    with pytest.raises((TypeError, ValueError)):
        cli._state_path(tmp_path.resolve(), "..", "processing-state.json")
    with pytest.raises(ValueError):
        cli._state_path(tmp_path.resolve(), str(RUN_ID), "../escape.json")


# --- P2-3: every published selection row must be source-version-bound ---


def test_selection_from_inventory_rejects_missing_source_version():
    roots = CanonicalIncludeRoots(("1000",))
    root_metadata = ConfluencePageMetadata("1000", "Root", "SPACE")
    assert root_metadata.source_version is None
    root_fact = InventoryRootCommit(RUN_ID, 0, "1000", root_metadata, roots)

    with pytest.raises(ValueError):
        cli._selection_payload_from_inventory(
            run_id=RUN_ID, facts=(root_fact,), max_pages=10,
            crawled_at="2026-08-10T00:00:00Z",
        )


def test_selection_from_inventory_accepts_bound_source_version():
    roots = CanonicalIncludeRoots(("1000",))
    root_metadata = ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1")
    root_fact = InventoryRootCommit(RUN_ID, 0, "1000", root_metadata, roots)

    selection = cli._selection_payload_from_inventory(
        run_id=RUN_ID, facts=(root_fact,), max_pages=10,
        crawled_at="2026-08-10T00:00:00Z",
    )

    assert selection["items"] == [{
        "page_id": "1000", "crawled_at": "2026-08-10T00:00:00Z",
        "expected_source_version": "1",
    }]


def test_load_subtree_selection_rejects_null_expected_source_version(tmp_path):
    rows = [{
        "page_id": "1000", "crawled_at": "2026-08-10T00:00:00Z",
        "expected_source_version": None,
    }]
    path = (tmp_path / "selection.json").resolve()
    path.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError):
        cli._load_subtree_selection(path, 10)


# --- P3-1: the configured root page must survive into the published selection ---


def test_assert_root_page_in_selection_rejects_missing_root():
    selection = {"items": [{"page_id": "2000", "crawled_at": "x", "expected_source_version": "1"}]}
    with pytest.raises(ValueError):
        cli._assert_root_page_in_selection("1000", selection)


def test_assert_root_page_in_selection_accepts_present_root():
    selection = {"items": [{"page_id": "1000", "crawled_at": "x", "expected_source_version": "1"}]}
    cli._assert_root_page_in_selection("1000", selection)


# --- P2-1: export must re-verify Draw.io raw evidence against disk ---


def _publish_drawio_attachment(raw_root: Path, *, attachment_id: str = "att12", body: bytes = b"<xml/>") -> tuple[str, int]:
    attachments_root = raw_root / "attachments"
    attachments_root.mkdir(parents=True, exist_ok=True)
    budget = MediaBodyStoreBudget(max_body_bytes=4096, max_total_bytes=1024 * 1024, minimum_free_disk_reserve_bytes=0)
    store = ConfluenceRawAttachmentStore(data_root=attachments_root, budget=budget)
    envelope = MediaAttachmentBodyEnvelope(
        format_version="1", evidence_kind="confluence_attachment_body",
        attachment_id=attachment_id, parent_page_id="1000", filename="diagram.drawio",
        source_version="3", http_status=200, body_encoding="base64", body_bytes=body,
    )
    store.publish_attachment(envelope=envelope)
    return hashlib.sha256(body).hexdigest(), len(body)


def _drawio_verify_profile():
    return {"max_response_bytes_per_request": 8388608, "minimum_free_disk_reserve_bytes": 0}


def test_verify_drawio_media_assets_accepts_matching_raw_artifact(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    content_hash, size = _publish_drawio_attachment(raw_root)
    asset = {
        "media_id": "m1",
        "raw_uri": f"raw://confluence/attachments/att12/{content_hash}",
        "content_hash": content_hash,
        "size_bytes": size,
    }
    config = cli.ConfluenceSubtreeCorpusConfig(max_pages=10, drawio_bytes=1024 * 1024)

    cli._verify_drawio_media_assets_on_disk(
        raw_root=raw_root, media_assets=[asset],
        profile=_drawio_verify_profile(), drawio_config=config,
    )


def test_verify_drawio_media_assets_fails_closed_when_artifact_missing(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    content_hash, size = _publish_drawio_attachment(raw_root)
    target = raw_root / "attachments" / "confluence" / "attachments" / "att12" / f"{content_hash}.json"
    assert target.exists()
    target.unlink()
    asset = {
        "media_id": "m1",
        "raw_uri": f"raw://confluence/attachments/att12/{content_hash}",
        "content_hash": content_hash,
        "size_bytes": size,
    }
    config = cli.ConfluenceSubtreeCorpusConfig(max_pages=10, drawio_bytes=1024 * 1024)

    with pytest.raises(ValueError):
        cli._verify_drawio_media_assets_on_disk(
            raw_root=raw_root, media_assets=[asset],
            profile=_drawio_verify_profile(), drawio_config=config,
        )


def test_verify_drawio_media_assets_fails_closed_when_declared_size_does_not_match(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    content_hash, size = _publish_drawio_attachment(raw_root)
    asset = {
        "media_id": "m1",
        "raw_uri": f"raw://confluence/attachments/att12/{content_hash}",
        "content_hash": content_hash,
        "size_bytes": size + 1,
    }
    config = cli.ConfluenceSubtreeCorpusConfig(max_pages=10, drawio_bytes=1024 * 1024)

    with pytest.raises(ValueError):
        cli._verify_drawio_media_assets_on_disk(
            raw_root=raw_root, media_assets=[asset],
            profile=_drawio_verify_profile(), drawio_config=config,
        )


def test_verify_drawio_media_assets_rejects_forged_raw_uri(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    content_hash, size = _publish_drawio_attachment(raw_root)
    asset = {
        "media_id": "m1",
        "raw_uri": f"raw://confluence/attachments/att12/{'0' * 64}",
        "content_hash": content_hash,
        "size_bytes": size,
    }
    config = cli.ConfluenceSubtreeCorpusConfig(max_pages=10, drawio_bytes=1024 * 1024)

    with pytest.raises(ValueError):
        cli._verify_drawio_media_assets_on_disk(
            raw_root=raw_root, media_assets=[asset],
            profile=_drawio_verify_profile(), drawio_config=config,
        )


def test_verify_drawio_media_assets_skips_when_no_assets(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    cli._verify_drawio_media_assets_on_disk(
        raw_root=raw_root, media_assets=[],
        profile=_drawio_verify_profile(), drawio_config=cli.ConfluenceSubtreeCorpusConfig(max_pages=10),
    )


# --- P1-2: forcing end-to-end test across all five phases, one state dir, one run id ---
#
# Real checkpoint state (SQLite), real raw-page-store layout, and real
# selection/processing/drawio-state binding all run through the production
# phase functions unmodified. Only two narrow seams are faked to keep this
# offline: the Confluence HTTP transport (page bodies come from an in-memory
# fixture instead of the network) and the chunking/tokenizer pipeline (this
# machine has no pinned BGE-M3 bundle -- see docs/FOUNDATION_EXTERNAL_GATE_
# RUNBOOK.md). Everything else -- run/generation identity, fingerprint
# binding, selection identity, processing-state binding, and drawio-state
# binding -- is the real production code.


class _FakeInventoryWindowPort:
    """Offline ConfluenceInventoryWindowPort: one root, one descendant."""

    def __init__(self, *, descendant_page_id: str, descendant_version: str) -> None:
        self._descendant_page_id = descendant_page_id
        self._descendant_version = descendant_version

    def fetch_root_metadata(self, *, space_key, root_page_id):
        return ConfluencePageMetadata(root_page_id, "Root", space_key, source_version="1")

    def fetch_descendants_window(self, *, space_key, root_page_id, start, page_size):
        metadata = ConfluencePageMetadata(
            self._descendant_page_id, "Child", space_key,
            parent_page_id=root_page_id, ancestor_page_ids=(root_page_id,),
            ancestor_titles=("Root",), source_version=self._descendant_version,
        )
        return ConfluenceInventoryWindow(items=(metadata,), start=0, limit=page_size, size=1, total_size=1)


class _FakeHttpInner:
    """Offline top-level transport double: page bodies keyed by page id."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self._pages = pages

    def get_bytes(self, *, path, query):
        page_id = path.rsplit("/", 1)[-1]
        if page_id not in self._pages:
            raise AssertionError(f"unexpected page fetch for {page_id!r}")
        return self._pages[page_id]

    def get_json(self, *, path, query):
        raise AssertionError("get_json is not exercised by this offline e2e test")

    def get_response_bytes(self, *, path, query):
        raise AssertionError("get_response_bytes is not exercised by this offline e2e test")


class _FakeRetryingTransport:
    """Passthrough replacing RetryingConfluenceHttpTransport: no retries, no pacing."""

    def __init__(self, *, inner, profile, monotonic_clock, sleeper, attempt_reserver) -> None:
        self._inner = inner

    def get_bytes(self, *, path, query):
        return self._inner.get_bytes(path=path, query=query)

    def get_json(self, *, path, query):
        return self._inner.get_json(path=path, query=query)

    def get_response_bytes(self, *, path, query):
        return self._inner.get_response_bytes(path=path, query=query)


class _FakeLiveSubtreeComposition:
    def __init__(self, *, checkpoint_run_port, raw_page_store, window_port, http_inner) -> None:
        self.checkpoint_run_port = checkpoint_run_port
        self.raw_page_store = raw_page_store
        self.http_inner = http_inner
        self.retry_profile = None
        self._window_port = window_port

    def inventory_use_case(self, *, max_search_pages):
        return ExecuteDurableConfluenceInventory(
            checkpoint_run_port=self.checkpoint_run_port,
            inventory_window_port_factory=lambda transport: self._window_port,
            inventory_transport_factory=lambda activation: object(),
        )

    def guarded_raw_page_store(self, *, activation):
        assert callable(getattr(activation, "guard_raw_publication", None))
        return self.raw_page_store

    def attachment_components(self, **_kwargs):
        raise AssertionError("this offline e2e test does not exercise Draw.io attachment fetch")


def _make_fake_compose_live_subtree(window_port, http_inner):
    def _fake_compose_live_subtree(*, raw_root, checkpoint_workspace, reliability_profile, max_search_pages, **_kwargs):
        return _FakeLiveSubtreeComposition(
            checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
            raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
            window_port=window_port,
            http_inner=http_inner,
        )

    return _fake_compose_live_subtree


def _confluence_page_json(*, page_id: str, title: str, space_key: str, version: int, html: str) -> bytes:
    payload = {
        "id": page_id, "type": "page", "title": title,
        "space": {"key": space_key},
        "version": {"number": version, "when": "2026-08-10T00:00:00Z"},
        "body": {"storage": {"value": html, "representation": "storage"}},
    }
    return json.dumps(payload).encode("utf-8")


def _fake_process_result(items):
    """Build a schema-valid CanonicalDocument/ChunkRecord pair per item.

    Field shapes (schema_version, acl_id, chunk_id, acl_tags, ...) mirror
    contracts/foundation/schemas/canonical_document.schema.json and
    chunk_record.schema.json exactly, so SubtreePacketExporter.publish's
    real (unmocked) schema validation accepts them.
    """
    count = len(items)
    documents = []
    chunks = []
    for item in items:
        document_id = f"confluence:page:{item.page_id}"
        documents.append({
            "schema_version": "1.0",
            "document_id": document_id,
            "source_system": "confluence",
            "source_type": "wiki_page",
            "page_id": item.page_id,
            "source_version": item.expected_source_version,
            "content_hash": hashlib.sha256(f"document-{item.page_id}".encode()).hexdigest(),
            "acl_id": "acl:restricted:unresolved",
            "crawled_at": item.crawled_at,
        })
        chunk_hex = hashlib.sha256(f"chunk-{item.page_id}".encode()).hexdigest()[:16]
        chunks.append({
            "schema_version": "1.0",
            "chunk_id": f"chunk:confluence:{chunk_hex}",
            "document_id": document_id,
            "source_system": "confluence",
            "source_type": "wiki_page",
            "text": f"Fixture body for {item.page_id}",
            "content_kind": "prose",
            "language": "unknown",
            "token_count": 4,
            "acl_tags": ["restricted:unresolved"],
            "content_hash": hashlib.sha256(f"chunk-body-{item.page_id}".encode()).hexdigest(),
            "chunker_version": "1.3.0",
        })
    documents = tuple(documents)
    chunks = tuple(chunks)
    page_metrics = tuple(
        ConfluencePageSetPageMetrics(ordinal, 1, 0, 0, (("paragraph", 1),))
        for ordinal in range(1, count + 1)
    )
    metrics = ConfluencePageSetMetrics(count, count, 0, count, count, 0, 0, (("paragraph", count),))
    return ConfluencePageSetResult(
        documents=documents, chunks=chunks, page_metrics=page_metrics, metrics=metrics,
        reference_intents_by_page=tuple((doc["document_id"], ()) for doc in documents),
    )


def test_five_phases_run_sequentially_against_one_state_dir_and_run_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    state = (tmp_path / "state").resolve()
    state.mkdir()
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    output_dir = (tmp_path / "packet").resolve()

    window_port = _FakeInventoryWindowPort(descendant_page_id="2000", descendant_version="3")
    http_inner = _FakeHttpInner({
        "1000": _confluence_page_json(page_id="1000", title="Root", space_key="SPACE", version=1, html="<p>Root body</p>"),
        "2000": _confluence_page_json(page_id="2000", title="Child", space_key="SPACE", version=3, html="<p>Child body</p>"),
    })
    monkeypatch.setattr(confluence_pkg, "compose_live_subtree", _make_fake_compose_live_subtree(window_port, http_inner))
    monkeypatch.setattr(retry_transport_module, "RetryingConfluenceHttpTransport", _FakeRetryingTransport)

    base = dict(
        max_pages=10, raw_root=str(raw_root), space_key="SPACE", root_page_id="1000",
        reliability_profile_path=str(APPROVED_PROFILE_PATH),
    )

    # Phase 1: inventory -- real checkpoint DB, real fingerprint/run-id, root included.
    # The first call starts the run and drives the underlying crawl loop to
    # completion inside one session, but (matching production: activation
    # snapshots are captured once and are not refreshed by later commits) it
    # reports the pre-crawl snapshot and cannot yet publish a selection. A
    # second, resumed call observes the now-complete state and publishes it --
    # this two-call polling shape is the real, intended operator flow.
    first_inventory_call = cli._inventory_phase(_args(**base), state)
    assert first_inventory_call["selected_pages"] == 0

    inventory_result = cli._inventory_phase(_args(**base, resume_unique=True), state)
    assert inventory_result["status"] == "complete"
    assert inventory_result["selected_pages"] == 2
    run_id = inventory_result["run_id"]

    selection_path = cli._state_path(state, run_id, "inventory-selection.json")
    selection = cli._read_json(selection_path)
    assert {row["page_id"] for row in selection["items"]} == {"1000", "2000"}
    assert selection["run_id"] == run_id and selection["generation_id"] == run_id

    # Phase 2: capture-pages -- real activation of the same run, real raw-store writes.
    capture_result = cli._capture_pages_phase(_args(**base, run_id=run_id), state)
    assert capture_result["status"] == "complete"
    assert capture_result["captured"] == 2

    raw_store = ConfluenceRawPageGenerationStore(raw_root=raw_root)
    for page_id in ("1000", "2000"):
        assert raw_store.resolve_page_path(run_id=CrawlRunId(run_id), page_id=page_id).exists()

    # Phase 3: process-pages -- chunking/tokenizer injected (no pinned bundle here);
    # everything else (selection binding, processing-state binding) is real.
    monkeypatch.setattr(cli, "_compose_page_processor", lambda _args, *, run_id, items: _fake_process_result(items))

    process_result = cli._process_pages_phase(_args(**base, run_id=run_id), state)
    assert process_result["status"] == "complete"
    assert process_result["page_count"] == 2

    processing_state = cli._read_json(cli._state_path(state, run_id, "processing-state.json"))
    assert processing_state["run_id"] == run_id
    assert processing_state["selection_identity"] == selection["selection_identity"]
    assert processing_state["failed_pages"] == 0

    # Re-running process-pages must replay identically, not re-mutate durable state.
    replay_result = cli._process_pages_phase(_args(**base, run_id=run_id), state)
    assert replay_result == process_result

    # Phase 4: capture-drawio -- zero references in this fixture corpus; still
    # binds and persists generation-scoped state for real.
    drawio_result = cli._capture_drawio_phase(_args(**base, run_id=run_id), state)
    assert drawio_result["status"] == "complete"
    assert drawio_result["drawio_references_observed"] == 0

    drawio_state = cli._read_json(cli._state_path(state, run_id, "drawio-state.json"))
    assert drawio_state["run_id"] == run_id
    assert drawio_state["selection_identity"] == selection["selection_identity"]

    # Phase 5: export -- reprocesses, compares against recorded state, publishes.
    export_result = cli._export_phase(_args(**base, run_id=run_id, output_dir=str(output_dir)), state)
    assert export_result["status"] == "complete"
    assert export_result["packet_published"] is True
    assert export_result["document_count"] == 2

    documents = (output_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(line)["page_id"] for line in documents} == {"1000", "2000"}

    # A second export at the same output directory must refuse to clobber.
    with pytest.raises(ValueError):
        cli._export_phase(_args(**base, run_id=run_id, output_dir=str(output_dir)), state)


_EXPECTED_ACTIVATION_FAILURE_CATEGORIES = {
    CheckpointRunSelectionFailureCategory.RUN_OPERATION_INVALID:
        "raw_generation_activation_run_operation_invalid",
    CheckpointRunSelectionFailureCategory.RUN_NOT_FOUND:
        "raw_generation_activation_run_not_found",
    CheckpointRunSelectionFailureCategory.RUN_NOT_RESUMABLE:
        "raw_generation_activation_run_not_resumable",
    CheckpointRunSelectionFailureCategory.RUN_MATCH_AMBIGUOUS:
        "raw_generation_activation_run_match_ambiguous",
    CheckpointRunSelectionFailureCategory.INCOMPLETE_RUN_CONFLICT:
        "raw_generation_activation_incomplete_run_conflict",
}


@pytest.mark.parametrize(
    ("source", "expected"),
    tuple(_EXPECTED_ACTIVATION_FAILURE_CATEGORIES.items()),
)
def test_activation_failure_preserves_locked_selection_category(source, expected):
    assert cli._activation_failure(CheckpointRunSelectionFailure(source)) == {
        "status": "failed",
        "failure_category": expected,
    }


def test_activation_failure_mapping_is_total_over_public_categories():
    public_categories = {
        value
        for name, value in vars(CheckpointRunSelectionFailureCategory).items()
        if name.isupper() and type(value) is str
    }
    assert public_categories == set(_EXPECTED_ACTIVATION_FAILURE_CATEGORIES)
    assert cli._ACTIVATION_FAILURE_CATEGORIES == (
        _EXPECTED_ACTIVATION_FAILURE_CATEGORIES
    )


def test_inventory_complete_activation_outcome_fails_closed():
    roots = CanonicalIncludeRoots(("1000",))
    snapshot = CrawlRunSnapshot(
        RUN_ID,
        RUN_ID,
        ConfluenceCrawlFingerprint._from_digest("a" * 64),
        CrawlRunStatus.INCOMPLETE,
        InventoryPhaseStatus.PENDING,
        roots,
        (IncludeRootProgress.ROOT_PENDING,),
    )
    assert cli._activation_failure(CheckpointRunInventoryComplete(snapshot)) == {
        "status": "failed",
        "failure_category": "raw_generation_activation_run_operation_invalid",
    }


def test_activation_methods_reject_malformed_and_hostile_results():
    class Hostile:
        @property
        def stream_inventory_occurrences(self):
            raise RuntimeError("must be sanitized")

    class NonCallable:
        stream_inventory_occurrences = object()
        pause_session = object()

    assert cli._activation_methods(None) is None
    assert cli._activation_methods(object()) is None
    assert cli._activation_methods(Hostile()) is None
    assert cli._activation_methods(NonCallable()) is None


class _InventoryPhaseSnapshot:
    run_id = RUN_ID

    class _Complete:
        value = "complete"

    inventory_phase = _Complete()


class _InventoryPhaseResult:
    snapshot = _InventoryPhaseSnapshot()
    status = "complete"


class _InventoryPhaseUseCase:
    def execute(self, *, request):
        return _InventoryPhaseResult()


class _ActivationContext:
    def __init__(self, outcome):
        self._outcome = outcome

    def __enter__(self):
        return self._outcome

    def __exit__(self, *_args):
        return False


class _InventoryPhaseComposition:
    def __init__(self, outcome):
        self.checkpoint_run_port = self
        self._outcome = outcome

    def inventory_use_case(self, *, max_search_pages):
        return _InventoryPhaseUseCase()

    def activate_raw_generation(self, request):
        return _ActivationContext(self._outcome)


def _inventory_phase_args(tmp_path):
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    return _args(
        run_id=None,
        raw_root=str(raw_root),
        reliability_profile_path=str(APPROVED_PROFILE_PATH),
    )


def test_inventory_stream_failure_pauses_and_does_not_publish(monkeypatch, tmp_path):
    calls = {"paused": 0, "published": 0}

    class FailingSession:
        def stream_inventory_occurrences(self, *, batch_size):
            raise ValueError("sanitized stream failure")

        def pause_session(self):
            calls["paused"] += 1

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    monkeypatch.setattr(
        confluence_pkg,
        "compose_live_subtree",
        lambda **_kwargs: _InventoryPhaseComposition(FailingSession()),
    )

    def unexpected_publication(*_args, **_kwargs):
        calls["published"] += 1
        raise AssertionError("publication must not run after stream failure")

    monkeypatch.setattr(cli, "_atomic_json", unexpected_publication)
    result = cli._inventory_phase(_inventory_phase_args(tmp_path), tmp_path.resolve())

    assert result == {"status": "failed", "failure_category": "inventory_stream"}
    assert calls == {"paused": 1, "published": 0}


def test_inventory_hostile_activation_fails_before_publication(monkeypatch, tmp_path):
    calls = {"published": 0}

    class HostileSession:
        @property
        def stream_inventory_occurrences(self):
            raise RuntimeError("must be sanitized")

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    monkeypatch.setattr(
        confluence_pkg,
        "compose_live_subtree",
        lambda **_kwargs: _InventoryPhaseComposition(HostileSession()),
    )

    def unexpected_publication(*_args, **_kwargs):
        calls["published"] += 1
        raise AssertionError("publication must not run")

    monkeypatch.setattr(cli, "_atomic_json", unexpected_publication)
    result = cli._inventory_phase(_inventory_phase_args(tmp_path), tmp_path.resolve())

    assert result == {
        "status": "failed",
        "failure_category": "raw_generation_activation_run_operation_invalid",
    }
    assert calls == {"published": 0}


def test_selection_publication_failure_uses_valid_inventory_fact(monkeypatch, tmp_path):
    calls = {"paused": 0, "published": 0}
    roots = CanonicalIncludeRoots(("1000",))
    fact = InventoryRootCommit(
        RUN_ID,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        roots,
    )

    class ValidSession:
        def stream_inventory_occurrences(self, *, batch_size):
            return iter((fact,))

        def pause_session(self):
            calls["paused"] += 1

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    monkeypatch.setattr(
        confluence_pkg,
        "compose_live_subtree",
        lambda **_kwargs: _InventoryPhaseComposition(ValidSession()),
    )

    def fail_publication(*_args, **_kwargs):
        calls["published"] += 1
        raise OSError("sanitized publication failure")

    monkeypatch.setattr(cli, "_atomic_json", fail_publication)
    result = cli._inventory_phase(_inventory_phase_args(tmp_path), tmp_path.resolve())

    assert result == {
        "status": "failed",
        "failure_category": "selection_publication",
    }
    assert calls == {"paused": 1, "published": 1}


def test_invalid_inventory_selection_is_not_mislabeled_as_publication(
    monkeypatch, tmp_path
):
    calls = {"paused": 0, "published": 0}
    roots = CanonicalIncludeRoots(("2000",))
    fact = InventoryRootCommit(
        RUN_ID,
        0,
        "2000",
        ConfluencePageMetadata("2000", "Other", "SPACE", source_version="1"),
        roots,
    )

    class ValidButWrongScopeSession:
        def stream_inventory_occurrences(self, *, batch_size):
            return iter((fact,))

        def pause_session(self):
            calls["paused"] += 1

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    monkeypatch.setattr(
        confluence_pkg,
        "compose_live_subtree",
        lambda **_kwargs: _InventoryPhaseComposition(
            ValidButWrongScopeSession()
        ),
    )

    def unexpected_publication(*_args, **_kwargs):
        calls["published"] += 1
        raise AssertionError("invalid selection must not be published")

    monkeypatch.setattr(cli, "_atomic_json", unexpected_publication)
    result = cli._inventory_phase(_inventory_phase_args(tmp_path), tmp_path.resolve())

    assert result == {
        "status": "failed",
        "failure_category": "inventory_selection_invalid",
    }
    assert calls == {"paused": 1, "published": 0}


class _CapturePhaseSession:
    def __init__(self, facts, *, stream_error=None):
        self._facts = facts
        self._stream_error = stream_error
        self.paused = 0
        self.completed = 0

    def stream_inventory_occurrences(self, *, batch_size):
        if self._stream_error is not None:
            raise self._stream_error
        return iter(self._facts)

    def pause_session(self):
        self.paused += 1

    def complete_session(self):
        self.completed += 1


class _CapturePhaseComposition:
    def __init__(self, outcome):
        self.checkpoint_run_port = self
        self._outcome = outcome
        self.http_inner = object()
        self.retry_profile = object()

    def activate_raw_generation(self, request):
        return _ActivationContext(self._outcome)

    def guarded_raw_page_store(self, *, activation):
        return object()


def _capture_phase_fixture(monkeypatch, tmp_path, session, *, capture_result=None,
                           capture_error=None):
    state = (tmp_path / "state").resolve()
    state.mkdir()
    raw_root = (tmp_path / "raw").resolve()
    raw_root.mkdir()
    selection_path = cli._state_path(
        state, str(RUN_ID), "inventory-selection.json"
    )
    cli._atomic_json(selection_path, _selection())
    calls = {"capture_constructed": 0, "capture_run": 0}

    class FakeCapture:
        def __init__(self, **_kwargs):
            calls["capture_constructed"] += 1

        def run(self, **_kwargs):
            calls["capture_run"] += 1
            if capture_error is not None:
                raise capture_error
            return capture_result

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.invalid/wiki")
    monkeypatch.setattr(
        confluence_pkg,
        "compose_live_subtree",
        lambda **_kwargs: _CapturePhaseComposition(session),
    )
    monkeypatch.setattr(
        retry_transport_module,
        "RetryingConfluenceHttpTransport",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        page_adapter_module,
        "ConfluenceDataCenterPageAdapter",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        orphan_inspector_module,
        "ConfluenceRawPageOrphanInspector",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        capture_pages_module,
        "CaptureConfluenceSubtreePages",
        FakeCapture,
    )
    args = _args(
        raw_root=str(raw_root),
        reliability_profile_path=str(APPROVED_PROFILE_PATH),
        selection_path=str(selection_path),
        stop_after_batches=None,
    )
    return args, state, calls


def _capture_inventory_fact():
    roots = CanonicalIncludeRoots(("1000",))
    return InventoryRootCommit(
        RUN_ID,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="7"),
        roots,
    )


def test_capture_stream_failure_pauses_once_before_capture_side_effects(
    monkeypatch, tmp_path
):
    session = _CapturePhaseSession(
        (), stream_error=ValueError("sanitized stream failure")
    )
    args, state, calls = _capture_phase_fixture(
        monkeypatch, tmp_path, session
    )

    result = cli._capture_pages_phase(args, state)

    assert result == {"status": "failed", "failure_category": "inventory_stream"}
    assert session.paused == 1
    assert session.completed == 0
    assert calls == {"capture_constructed": 0, "capture_run": 0}


@pytest.mark.parametrize(
    ("complete", "expected_status", "expected_pauses", "expected_completions"),
    ((True, "complete", 0, 1), (False, "stopped", 1, 0)),
)
def test_capture_result_closes_checkpoint_session_by_result(
    monkeypatch,
    tmp_path,
    complete,
    expected_status,
    expected_pauses,
    expected_completions,
):
    session = _CapturePhaseSession((_capture_inventory_fact(),))
    capture_result = PageCaptureResult(
        captured=1 if complete else 0,
        replayed=0,
        skipped=0,
        failed=0,
        stopped=not complete,
        expected_total=1,
    )
    args, state, calls = _capture_phase_fixture(
        monkeypatch, tmp_path, session, capture_result=capture_result
    )

    result = cli._capture_pages_phase(args, state)

    assert result["status"] == expected_status
    assert session.paused == expected_pauses
    assert session.completed == expected_completions
    assert calls == {"capture_constructed": 1, "capture_run": 1}


def test_capture_failure_is_not_mislabeled_and_pauses_for_resume(
    monkeypatch, tmp_path
):
    class CaptureFailure(RuntimeError):
        pass

    session = _CapturePhaseSession((_capture_inventory_fact(),))
    args, state, calls = _capture_phase_fixture(
        monkeypatch,
        tmp_path,
        session,
        capture_error=CaptureFailure("sanitized capture failure"),
    )

    with pytest.raises(CaptureFailure):
        cli._capture_pages_phase(args, state)

    # Capture failures deliberately pause the durable run so that a separately
    # authorized phase resume can continue from committed page acknowledgements.
    assert session.paused == 1
    assert session.completed == 0
    assert calls == {"capture_constructed": 1, "capture_run": 1}


def test_phase_failure_is_logged_even_though_stdout_stays_a_fixed_contract(
    capsys, caplog, tmp_path
):
    """The one-line stdout contract hides *why* a phase failed.

    Every exception is collapsed into the same hardcoded payload, and the
    wrapper reads a `failure_category` key this CLI never writes, so a real
    failure reached operators as the single word "phase" with no trace
    anywhere. stdout must stay byte-for-byte identical, but the cause has to
    survive somewhere.
    """
    import logging

    with caplog.at_level(logging.ERROR, logger="knowledgenexus.foundation.cli.confluence_subtree_corpus"):
        result = main(["capture-drawio", "--state-dir", str(tmp_path), "--max-pages", "5000"])

    assert result == 2
    # The machine-read contract is unchanged.
    assert capsys.readouterr().out == '{"status":"failed","error":"configuration"}\n'
    # ...but the cause is now recoverable.
    assert any(record.exc_info for record in caplog.records), "traceback was not logged"
    assert "capture-drawio" in caplog.text
