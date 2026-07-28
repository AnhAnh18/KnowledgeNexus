from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import export_confluence_one_page_snapshot as cli
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHUNK_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"
)
JIRA_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"
)
TIMESTAMP = "2026-07-24T00:00:00Z"
GENERATED_AT = "2026-07-24T00:00:00Z"


def test_full_cli_composes_projects_and_publishes_offline(
    tmp_path: Path,
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6G-C attempted network access")

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
                "space": {"key": "SVMC"},
                "version": {"number": 9, "when": TIMESTAMP},
                "body": {
                    "storage": {
                        "value": "<h2>Design</h2><p>Deterministic full snapshot.</p>",
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
                "evidence_kind": "synthetic_fixture",
                "restriction_observations": [
                    {
                        "source_page_id": source_page_id,
                        "http_status": 200,
                        "classification": "unrestricted",
                        "users": [],
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
    export_root = tmp_path / "export"
    (export_root / ONE_PAGE_DATASET_NAME).mkdir(parents=True)
    before_source_tree = {
        raw_page: raw_page.read_bytes(),
        sidecar_path: sidecar_path.read_bytes(),
    }

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
            "--generated-at",
            GENERATED_AT,
            "--export-root",
            str(export_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "status": "success",
        "restriction_evidence_kind": "synthetic_fixture",
        "real_captured_evidence": False,
        "network_used": False,
        "credentials_used": False,
        "restriction_ancestry_bound": True,
        "acl_record_schema_valid": True,
        "chunks_schema_valid": True,
        "canonical_unchanged": True,
        "relations_unchanged": True,
        "chunk_non_acl_fields_unchanged": True,
        "chunk_acl_tags_match_acl_record": True,
        "deterministic_repeat": True,
        "projection_deterministic": True,
        "raw_page_unchanged": True,
        "sidecar_unchanged": True,
        "output_files_created": True,
        "manifest_schema_valid": True,
        "manifest_counts_match": True,
        "records_match_projection": True,
        "deferred_streams_empty": True,
        "final_file_set_valid": True,
        "quality_report_complete": True,
        "quality_report_unchanged": True,
        "latest_pointer_valid": True,
    }

    for path, before_bytes in before_source_tree.items():
        assert path.read_bytes() == before_bytes

    dataset_root = export_root / ONE_PAGE_DATASET_NAME
    published_dirs = [p for p in dataset_root.iterdir() if p.is_dir()]
    assert len(published_dirs) == 1
    final_path = published_dirs[0]
    assert {entry.name for entry in final_path.iterdir()} == {
        "documents.jsonl",
        "chunks.jsonl",
        "relations.jsonl",
        "acl.jsonl",
        "media_assets.jsonl",
        "symbols.jsonl",
        "sync_state.jsonl",
        "tombstones.jsonl",
        "manifest.json",
        "quality_report.md",
    }

    for forbidden in (
        page_id,
        "Fixture Foundation",
        "fixture-crawler",
        str(tmp_path),
        str(tokenizer_assets_dir),
        str(export_root),
        "space:SVMC",
    ):
        assert forbidden not in captured.out
