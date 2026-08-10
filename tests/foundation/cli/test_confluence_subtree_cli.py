import argparse

from knowledgenexus.foundation.cli import confluence_subtree_corpus as cli
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_content import NormalizationReferenceIntent
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetResult,
)


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
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_help_exits_zero_without_failure_payload(capsys):
    assert main(["--help"]) == 0
    assert '"status":"failed"' not in capsys.readouterr().out


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


def test_operator_page_cap_is_bound_into_durable_profile():
    profile = {"max_pages_per_run": 10_000, "profile_id": "profile"}
    bounded = cli._bounded_reliability_profile(_args(max_pages=5_000), profile)
    assert bounded["max_pages_per_run"] == 5_000
    assert profile["max_pages_per_run"] == 10_000


def test_state_path_rejects_traversal_run_and_unknown_artifact(tmp_path):
    import pytest
    with pytest.raises((TypeError, ValueError)):
        cli._state_path(tmp_path.resolve(), "..", "processing-state.json")
    with pytest.raises(ValueError):
        cli._state_path(tmp_path.resolve(), str(RUN_ID), "../escape.json")
