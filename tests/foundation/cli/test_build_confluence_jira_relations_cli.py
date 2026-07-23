from __future__ import annotations

import ast
import json
import socket
import urllib.request
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import build_confluence_jira_relations as cli
from knowledgenexus.foundation.domain.models import (
    ConfluenceJiraRelationError,
    ConfluenceJiraRelationFailureCategory,
    ConfluenceJiraRelationResult,
    JiraRelationQualityObservation,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHUNK_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"
)
JIRA_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"
)
CREATED_AT = "2026-07-22T00:00:00Z"
UPDATED_AT = "2026-07-20T01:02:03Z"


def _argv() -> list[str]:
    return [
        "--page-id",
        "SENSITIVE-PAGE",
        "--raw-root",
        "C:/SENSITIVE/RAW",
        "--profile-path",
        "C:/SENSITIVE/CHUNK.yaml",
        "--tokenizer-assets-dir",
        "C:/SENSITIVE/ASSETS",
        "--jira-profile-path",
        "C:/SENSITIVE/JIRA.yaml",
        "--crawled-at",
        "2026-07-22T00:00:00Z",
        "--relation-created-at",
        "2026-07-22T00:00:01Z",
    ]


def _result(*, relations: int = 1) -> ConfluenceJiraRelationResult:
    relation_records = tuple(
        {"relation_id": f"SENSITIVE-RELATION-{index}"}
        for index in range(relations)
    )
    keys = ["SENSITIVE-KEY"] if relations else []
    ids = ["SENSITIVE-RELATION-0"] if relations else []
    return ConfluenceJiraRelationResult(
        enriched_canonical_document={"jira_keys": keys, "relation_ids": ids},
        enriched_chunks=(
            {
                "chunk_id": "SENSITIVE-CHUNK",
                "text": "SENSITIVE-TEXT",
                "jira_keys": keys,
                "relation_ids": ids,
                "acl_tags": ["restricted:unresolved"],
            },
        ),
        relations=relation_records,
        quality_observation=JiraRelationQualityObservation(
            unique_key_like_candidates=tuple(keys),
            allowlisted_keys=tuple(keys),
            outside_allowlist_keys=(),
        ),
        metrics={
            "candidate_occurrences": relations,
            "allowlisted_unique_count": relations,
            "outside_allowlist_unique_count": 0,
            "relations_total": relations,
        },
    )


def _outcome(*, relations: int = 1) -> cli._RunOutcome:
    return cli._RunOutcome(
        result=_result(relations=relations),
        deterministic_repeat=True,
        chunk_identity_content_unchanged=True,
        acl_unchanged=True,
    )


def test_success_prints_aggregate_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome())

    assert cli.main(_argv()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "success",
        "relation_type": "mentions_jira_key",
        "candidate_count": 1,
        "allowlisted_count": 1,
        "outside_allowlist_count": 0,
        "relation_count": 1,
        "zero_relations_valid": True,
        "schema_valid": True,
        "chunk_identity_content_unchanged": True,
        "acl_unchanged": True,
        "deterministic_repeat": True,
        "network_used": False,
        "output_files_created": False,
    }
    assert "SENSITIVE" not in captured.out


def test_zero_relation_success_is_valid(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: _outcome(relations=0))

    assert cli.main(_argv()) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["relation_count"] == 0
    assert summary["zero_relations_valid"] is True


def test_missing_argument_does_not_echo_inputs(capsys) -> None:
    assert cli.main(["--page-id", "SENSITIVE-PAGE"]) == cli.EXIT_CONFIGURATION

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "configuration",
    }
    assert "SENSITIVE" not in captured.err


def test_relation_failure_prints_only_category(monkeypatch, capsys) -> None:
    def fail(args: object) -> object:
        raise ConfluenceJiraRelationError(
            ConfluenceJiraRelationFailureCategory.RELATION_ID_COLLISION
        )

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_RELATION
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "category": "relation_id_collision",
    }


@pytest.mark.parametrize(
    "outcome",
    [
        cli._RunOutcome(_result(), False, True, True),
        cli._RunOutcome(_result(), True, False, True),
        cli._RunOutcome(_result(), True, True, False),
    ],
)
def test_acceptance_failure_cannot_publish_false_pass(
    outcome: cli._RunOutcome,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "_run", lambda args: outcome)

    assert cli.main(_argv()) == cli.EXIT_RELATION
    assert json.loads(capsys.readouterr().err) == {
        "status": "failed",
        "category": "acceptance_invariant",
    }


def test_unexpected_exception_is_sanitized(monkeypatch, capsys) -> None:
    def fail(args: object) -> object:
        raise RuntimeError("SENSITIVE-TEXT C:/SENSITIVE/RAW")

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(_argv()) == cli.EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "status": "failed",
        "category": "unexpected",
    }
    assert "SENSITIVE" not in captured.err


def test_cli_imports_no_http_transport_or_jira_client() -> None:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any("confluence_http_transport" in name for name in imports)
    assert not any("jira" in name.lower() and "profile" not in name.lower() and "relation" not in name.lower() for name in imports)


def test_real_bundle_composes_synthetic_relation_offline_without_writes(
    tmp_path: Path,
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6E acceptance path attempted network access")

    monkeypatch.setattr(urllib.request, "build_opener", forbid_network)
    monkeypatch.setattr(urllib.request, "urlopen", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)
    monkeypatch.setattr(socket, "socket", forbid_network)

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
                "version": {"number": 9, "when": UPDATED_AT},
                "body": {
                    "storage": {
                        "value": (
                            "<h2>Design</h2><p>SHA-256 tracking.</p>"
                            '<ac:structured-macro ac:name="jira">'
                            '<ac:parameter ac:name="key">SVMCSPEN-42</ac:parameter>'
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
            str(CHUNK_PROFILE_PATH),
            "--tokenizer-assets-dir",
            str(tokenizer_assets_dir),
            "--jira-profile-path",
            str(JIRA_PROFILE_PATH),
            "--crawled-at",
            CREATED_AT,
            "--relation-created-at",
            CREATED_AT,
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "status": "success",
        "relation_type": "mentions_jira_key",
        "candidate_count": 2,
        "allowlisted_count": 1,
        "outside_allowlist_count": 1,
        "relation_count": 1,
        "zero_relations_valid": True,
        "schema_valid": True,
        "chunk_identity_content_unchanged": True,
        "acl_unchanged": True,
        "deterministic_repeat": True,
        "network_used": False,
        "output_files_created": False,
    }
    after_tree = {
        path.relative_to(tmp_path): path.read_bytes() if path.is_file() else None
        for path in tmp_path.rglob("*")
    }
    assert after_tree == before_tree
    serialized = json.dumps(summary, sort_keys=True)
    for forbidden in (
        page_id,
        "SVMCSPEN-42",
        "SHA-256",
        "Fixture Foundation",
        "SPACE",
        str(tmp_path),
        str(tokenizer_assets_dir),
        "chunk:confluence",
        "content_hash",
    ):
        assert forbidden not in serialized
