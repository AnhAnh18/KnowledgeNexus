from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import materialize_confluence_acl as cli

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHUNK_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"
)
JIRA_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"
)
TIMESTAMP = "2026-07-24T00:00:00Z"


@pytest.mark.parametrize(
    ("evidence_kind", "classification", "http_status", "users", "real_evidence"),
    [
        ("captured_m6b_result", "unrestricted", 200, [], True),
        (
            "synthetic_fixture",
            "restricted",
            200,
            [{"userKey": "FixtureUser"}],
            False,
        ),
        ("synthetic_fixture", "unavailable", 404, [], False),
    ],
)
def test_full_c2_composition_uses_exact_local_bundle_offline_without_writes(
    tmp_path: Path,
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    evidence_kind: str,
    classification: str,
    http_status: int,
    users: list[dict[str, str]],
    real_evidence: bool,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6F-C2 attempted network access")

    monkeypatch.setattr(socket, "socket", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    page_id = "1000"
    raw_page = tmp_path / "raw" / "confluence" / "pages" / f"{page_id}.json"
    raw_page.parent.mkdir(parents=True)
    raw_page.write_text(
        json.dumps(
            {
                "id": page_id,
                "type": "page",
                "title": "Fixture Foundation",
                "ancestors": [{"id": "800"}, {"id": "900"}],
                "space": {"key": "SPACE"},
                "version": {"number": 9, "when": TIMESTAMP},
                "body": {
                    "storage": {
                        "value": "<h2>Design</h2><p>Deterministic ACL.</p>",
                        "representation": "storage",
                    }
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    sidecar_path = tmp_path / "restriction-sidecar.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "evidence_kind": evidence_kind,
                "restriction_observations": [
                    {
                        "source_page_id": source_page_id,
                        "http_status": http_status,
                        "classification": classification,
                        "users": users,
                        "groups": [],
                    }
                    for source_page_id in ("800", "900", page_id)
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    before_tree = _snapshot(tmp_path)

    exit_code = cli.main(
        [
            "--page-id",
            page_id,
            "--raw-root",
            str(tmp_path / "raw"),
            "--profile-path",
            str(CHUNK_PROFILE_PATH),
            "--tokenizer-assets-dir",
            str(tokenizer_assets_dir),
            "--jira-profile-path",
            str(JIRA_PROFILE_PATH),
            "--crawled-at",
            TIMESTAMP,
            "--relation-created-at",
            TIMESTAMP,
            "--restriction-sidecar-path",
            str(sidecar_path),
            "--crawler-identity",
            "fixture-crawler",
            "--acl-extracted-at",
            TIMESTAMP,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "success",
        "restriction_evidence_kind": evidence_kind,
        "real_captured_evidence": real_evidence,
        "restriction_ancestry_bound": True,
        "acl_record_schema_valid": True,
        "chunks_schema_valid": True,
        "canonical_unchanged": True,
        "relations_unchanged": True,
        "chunk_non_acl_fields_unchanged": True,
        "chunk_acl_tags_match_acl_record": True,
        "deterministic_repeat": True,
        "raw_page_unchanged": True,
        "sidecar_unchanged": True,
        "network_used": False,
        "output_files_created": False,
    }
    assert _snapshot(tmp_path) == before_tree
    for forbidden in (
        page_id,
        "Fixture Foundation",
        "SPACE",
        "fixture-crawler",
        "FixtureUser",
        str(tmp_path),
        str(tokenizer_assets_dir),
        "restricted:unresolved",
        "space:SPACE",
    ):
        assert forbidden not in captured.out


def _snapshot(root: Path) -> dict[Path, bytes | None]:
    return {
        path.relative_to(root): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }
