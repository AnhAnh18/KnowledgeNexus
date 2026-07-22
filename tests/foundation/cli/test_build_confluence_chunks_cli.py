from __future__ import annotations

import ast
import json
import socket
import urllib.request
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import build_confluence_chunks as cli
from knowledgenexus.foundation.domain.models import (
    ChunkingResult,
    ConfluenceChunkingError,
    ConfluenceChunkingFailureCategory,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


def _argv() -> list[str]:
    return [
        "--page-id",
        "SENSITIVE-PAGE",
        "--raw-root",
        "C:/SENSITIVE/RAW",
        "--profile-path",
        "C:/SENSITIVE/PROFILE.yaml",
        "--tokenizer-assets-dir",
        "C:/SENSITIVE/ASSETS",
        "--crawled-at",
        "2026-07-22T00:00:00Z",
    ]


def _outcome() -> cli._RunOutcome:
    result = ChunkingResult(
        records=(
            {
                "chunk_id": "SECRET-ID",
                "text": "SECRET-TEXT",
                "acl_tags": ["restricted:unresolved"],
            },
        ),
        metrics={
            "chunks_over_hard_max": 0,
            "maximum_token_count": 27,
        },
    )
    return cli._RunOutcome(
        result=result,
        deterministic_repeat=True,
        active_profile="medium",
        chunker_version="1.2.0",
    )


def test_success_prints_aggregate_only_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome())

    assert cli.main(_argv()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "success",
        "profile": "medium",
        "chunker_version": "1.2.0",
        "chunk_count": 1,
        "schema_valid": True,
        "maximum_token_count": 27,
        "chunks_over_hard_max": 0,
        "all_acl_tags_default_deny": True,
        "deterministic_repeat": True,
        "network_used": False,
        "output_files_created": False,
    }
    assert "SECRET" not in captured.out
    assert "SENSITIVE" not in captured.out


def test_missing_argument_never_echoes_argv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--page-id", "SENSITIVE-PAGE"]) == cli.EXIT_CONFIGURATION

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "configuration",
    }
    assert "SENSITIVE" not in captured.err


def test_chunking_failure_prints_only_category(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise ConfluenceChunkingError(
            ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_ROW
        )

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_CHUNKING
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "unsplittable_table_row",
    }
    assert "SENSITIVE" not in captured.err


@pytest.mark.parametrize(
    "outcome",
    [
        cli._RunOutcome(
            result=ChunkingResult(
                records=({"acl_tags": ["restricted:unresolved"]},),
                metrics={"chunks_over_hard_max": 0, "maximum_token_count": 1},
            ),
            deterministic_repeat=False,
            active_profile="medium",
            chunker_version="1.2.0",
        ),
        cli._RunOutcome(
            result=ChunkingResult(
                records=({"acl_tags": ["restricted:unresolved"]},),
                metrics={"chunks_over_hard_max": 1, "maximum_token_count": 1},
            ),
            deterministic_repeat=True,
            active_profile="medium",
            chunker_version="1.2.0",
        ),
        cli._RunOutcome(
            result=ChunkingResult(
                records=({"acl_tags": ["space:SPACE"]},),
                metrics={"chunks_over_hard_max": 0, "maximum_token_count": 1},
            ),
            deterministic_repeat=True,
            active_profile="medium",
            chunker_version="1.2.0",
        ),
    ],
)
def test_acceptance_invariant_failure_cannot_publish_a_false_pass(
    outcome: cli._RunOutcome,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: outcome)

    assert cli.main(_argv()) == cli.EXIT_CHUNKING
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "category": "acceptance_invariant",
    }


def test_unexpected_exception_cannot_disclose_source_or_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(args: object) -> object:
        raise RuntimeError("SECRET-TEXT C:/SENSITIVE/RAW")

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "unexpected",
    }
    assert "SECRET" not in captured.err
    assert "SENSITIVE" not in captured.err


def test_cli_requires_every_explicit_operator_input() -> None:
    args = cli._parse_args(_argv())

    assert args.page_id == "SENSITIVE-PAGE"
    assert args.raw_root == "C:/SENSITIVE/RAW"
    assert args.profile_path == "C:/SENSITIVE/PROFILE.yaml"
    assert args.tokenizer_assets_dir == "C:/SENSITIVE/ASSETS"
    assert args.crawled_at == "2026-07-22T00:00:00Z"


def test_cli_module_does_not_import_network_transport() -> None:
    source_path = Path(cli.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "urllib",
        "http",
        "socket",
        "requests",
        "confluence_http_transport",
        "confluence_data_center_inventory_adapter",
    )
    assert all(
        not any(term in module for term in forbidden)
        for module in imported
    )


def test_real_pinned_bundle_composes_full_offline_pipeline_without_writes(
    tmp_path: Path,
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6D-D acceptance path attempted network access")

    monkeypatch.setattr(urllib.request, "build_opener", forbid_network)
    monkeypatch.setattr(urllib.request, "urlopen", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    page_id = "1000"
    raw_page = tmp_path / "confluence" / "pages" / f"{page_id}.json"
    raw_page.parent.mkdir(parents=True)
    raw_page.write_text(
        json.dumps(
            {
                "id": page_id,
                "type": "page",
                "title": "Fixture Foundation",
                "space": {"key": "SPACE"},
                "version": {"number": 9, "when": "2026-07-20T01:02:03Z"},
                "body": {
                    "storage": {
                        "value": (
                            "<h2>Design</h2><p>Deterministic foundation body.</p>"
                            '<ac:structured-macro ac:name="code">'
                            "<ac:plain-text-body>line one\nline two</ac:plain-text-body>"
                            "</ac:structured-macro>"
                        ),
                        "representation": "storage",
                    }
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    before_tree = {
        path.relative_to(tmp_path): path.read_bytes() if path.is_file() else None
        for path in tmp_path.rglob("*")
    }

    exit_code = cli.main(
        [
            "--page-id",
            page_id,
            "--raw-root",
            str(tmp_path),
            "--profile-path",
            str(PROFILE_PATH),
            "--tokenizer-assets-dir",
            str(tokenizer_assets_dir),
            "--crawled-at",
            "2026-07-22T00:00:00Z",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "success"
    assert summary["profile"] == "medium"
    assert summary["chunker_version"] == "1.2.0"
    assert summary["chunk_count"] == 2
    assert summary["schema_valid"] is True
    assert summary["chunks_over_hard_max"] == 0
    assert summary["all_acl_tags_default_deny"] is True
    assert summary["deterministic_repeat"] is True
    assert summary["network_used"] is False
    assert summary["output_files_created"] is False
    after_tree = {
        path.relative_to(tmp_path): path.read_bytes() if path.is_file() else None
        for path in tmp_path.rglob("*")
    }
    assert after_tree == before_tree
    serialized = json.dumps(summary, sort_keys=True)
    for forbidden in (
        page_id,
        "Fixture Foundation",
        "Deterministic foundation body",
        "SPACE",
        str(tmp_path),
        str(tokenizer_assets_dir),
        "chunk:confluence",
        "content_hash",
    ):
        assert forbidden not in serialized
