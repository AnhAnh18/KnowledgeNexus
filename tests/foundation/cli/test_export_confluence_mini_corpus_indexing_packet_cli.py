from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import (
    export_confluence_mini_corpus_indexing_packet as cli,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetResult,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from tests.fixtures.foundation.record_factories import (
    build_sample_chunk_record,
    build_sample_document_record,
)


def _result() -> ConfluencePageSetResult:
    document = build_sample_document_record()
    chunk = build_sample_chunk_record()
    chunk["acl_tags"] = ["restricted:unresolved"]
    page_metric = ConfluencePageSetPageMetrics(
        page_ordinal=1,
        chunk_count=1,
        warning_count=0,
        reference_intent_count=0,
        content_kind_counts=(("prose", 1),),
    )
    return ConfluencePageSetResult(
        documents=(document,),
        chunks=(chunk,),
        page_metrics=(page_metric,),
        metrics=ConfluencePageSetMetrics(
            requested_pages=1,
            succeeded_pages=1,
            failed_pages=0,
            document_count=1,
            chunk_count=1,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(("prose", 1),),
        ),
    )


def test_packet_publish_writes_exact_deterministic_indexing_files(tmp_path: Path) -> None:
    result = _result()
    cli._validate_result(result, validator=FoundationSchemaValidator())

    first = tmp_path / "first"
    second = tmp_path / "second"
    cli._publish_packet(output_dir=first, result=result, chunker_version="1.2.0")
    cli._publish_packet(output_dir=second, result=result, chunker_version="1.2.0")

    assert {path.name for path in first.iterdir()} == {
        "documents.jsonl",
        "chunks.jsonl",
        "packet_summary.json",
    }
    for name in ("documents.jsonl", "chunks.jsonl", "packet_summary.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    documents = [json.loads(line) for line in (first / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    chunks = [json.loads(line) for line in (first / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((first / "packet_summary.json").read_text(encoding="utf-8"))
    assert len(documents) == len(chunks) == 1
    assert chunks[0]["acl_tags"] == ["restricted:unresolved"]
    assert summary["format_version"] == "m8ax-indexing-packet-v1"
    assert summary["document_count"] == summary["chunk_count"] == 1
    assert set(summary["files"]) == {"documents.jsonl", "chunks.jsonl"}


def test_packet_publish_never_overwrites_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "packet"
    target.mkdir()
    marker = target / "owner.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(Exception):
        cli._publish_packet(
            output_dir=target,
            result=_result(),
            chunker_version="1.2.0",
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_output_directory_must_be_outside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_REPOSITORY_ROOT", tmp_path)
    parent = tmp_path / "operator"
    parent.mkdir()
    with pytest.raises(Exception):
        cli._safe_output_directory(str(parent / "packet"))


def test_packet_failure_removes_owned_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_write(_path: Path, _records: tuple[dict[str, object], ...]) -> None:
        raise OSError("fixture detail must not escape")

    monkeypatch.setattr(cli, "_write_jsonl", fail_write)
    with pytest.raises(Exception) as raised:
        cli._publish_packet(
            output_dir=tmp_path / "packet",
            result=_result(),
            chunker_version="1.2.0",
        )

    assert str(raised.value) == ""
    assert not tuple(tmp_path.glob(".*.tmp"))
    assert not (tmp_path / "packet").exists()


def test_export_boundary_rejects_non_default_deny_chunks() -> None:
    result = _result()
    result.chunks[0]["acl_tags"] = ["space:SPACE"]

    with pytest.raises(Exception):
        cli._validate_result(result, validator=FoundationSchemaValidator())


def test_help_preserves_standard_success_semantics(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err == ""


def test_failure_output_is_aggregate_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "category": "configuration",
        "status": "failed",
    }


def _valid_operator_args(tmp_path: Path, *, output_dir: Path) -> list[str]:
    return [
        "--data-root", str(tmp_path / "data"),
        "--run-id", "11111111-1111-4111-8111-111111111111",
        "--selection-path", str(tmp_path / "selection.json"),
        "--profile-path", str(tmp_path / "profile.yaml"),
        "--tokenizer-assets-dir", str(tmp_path / "tokenizer"),
        "--output-dir", str(output_dir),
    ]


def test_relative_profile_path_is_configuration_not_unexpected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Regression: MiniCorpusOperatorInputError raised by the shared
    # safe_mini_corpus_path() helper used to be a different class than this
    # module's own private _ConfigurationError, so a rejected relative
    # --profile-path fell through to the generic "unexpected" category
    # instead of "configuration".
    args = _valid_operator_args(tmp_path, output_dir=tmp_path / "out" / "packet")
    (tmp_path / "out").mkdir()
    args[args.index("--profile-path") + 1] = "./relative/profile.yaml"

    exit_code = cli.main(args)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "category": "configuration",
        "status": "failed",
    }


def test_missing_output_parent_is_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "absent_parent" / "packet"
    args = _valid_operator_args(tmp_path, output_dir=output_dir)

    exit_code = cli.main(args)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "category": "configuration",
        "status": "failed",
    }


def test_existing_output_target_is_rejected_as_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "packet"
    output_dir.mkdir()
    args = _valid_operator_args(tmp_path, output_dir=output_dir)

    exit_code = cli.main(args)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "category": "configuration",
        "status": "failed",
    }
