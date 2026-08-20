from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.m10_snapshot import M10QualityReportInput
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import (
    FullSnapshotStagingCompleter,
    M10QualityCompletionError,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import FullSnapshotStagingWriter
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)


def _scopes():
    return {"confluence": {"source_id": "src", "space_keys": ["SVMC"], "root_page_ids": ["123"], "page_ids": ["123"]}}


def _quality() -> M10QualityReportInput:
    return M10QualityReportInput(
        "medium", "provisional_until_benchmark", "1.3.0",
        {"documents": 1, "chunks": 1, "relations": 1, "acl": 1, "media_assets": 0, "symbols": 0, "sync_state": 0, "tombstones": 0},
        {"confluence": {"source_id": "src", "space_keys": ("SVMC",), "root_page_ids": ("123",), "page_ids": ("123",)}},
        {"relations_total": 1, "resolved": 0, "unresolved": 1, "unresolved_without_jira_api": 1, "deferred_mvp": 0, "unresolved_target": 0},
        {"documents_total": 1, "documents_with_acl": 1, "restricted_documents": 0, "default_deny_chunks": 0},
        {"assets_total": 0, "processed": 0, "failed": 0, "not_processed": 0},
        {"symbols_total": 0, "resolved": 0},
        {"rows_total": 0, "active": 0, "pages": 0, "attachments": 0, "files": 0, "repos": 0},
        {"rows_total": 0, "initial_empty": 1},
        {"schema_validation": True, "counts_match": True, "tombstones_empty": True, "projection_consistency": True},
    )


def _write(staging: Path, *, tombstones=(), source_scopes=None):
    return FullSnapshotStagingWriter.write(
        staging_path=staging, validator=FoundationSchemaValidator(), dataset_version="v20260805-000000-000000Z", generated_at="2026-08-05T00:00:00Z", config_hash="a" * 64, chunker_version="1.3.0", schemas_version="1.0",
        documents=[build_sample_document_record()], chunks=[build_sample_chunk_record()], relations=[build_sample_relation_record()], acl=[build_sample_acl_record()], media_assets=[], symbols=[], sync_state=[], tombstones=tombstones, source_scopes=source_scopes or _scopes(),
    )


def _complete(staging: Path, *, quality=None, **kwargs):
    return FullSnapshotStagingCompleter.complete(staging_path=staging, validator=FoundationSchemaValidator(), m10_quality=quality or _quality(), **kwargs)


def test_m10_quality_report_has_exact_twelve_sections_and_is_deterministic(tmp_path):
    first = tmp_path / "first"; second = tmp_path / "second"
    _write(first); _write(second)
    _complete(first); _complete(second)
    first_bytes = (first / "quality_report.md").read_bytes()
    assert first_bytes == (second / "quality_report.md").read_bytes()
    report = first_bytes.decode()
    sections = ["Snapshot", "Active Profiles", "Record Counts", "Jira Relation Quality", "ACL Quality", "Media Quality", "Symbol Quality", "Sync State", "Tombstones", "Completion Checks", "Publication State", "Scope"]
    assert [report.index(f"## {section}") for section in sections] == sorted(report.index(f"## {section}") for section in sections)
    assert report.count("## ") == 12
    assert "PENDING_AT_REPORT_COMPLETION" in report
    assert "space:SVMC" not in report and "config_hash" not in report


def test_m10_quality_rejects_legacy_quality_or_fake_validator_before_filesystem(tmp_path):
    staging = tmp_path / "missing"
    with pytest.raises(M10QualityCompletionError):
        FullSnapshotStagingCompleter.complete(staging_path=staging, validator=object(), m10_quality=_quality())
    _write(staging)
    with pytest.raises(M10QualityCompletionError):
        FullSnapshotStagingCompleter.complete(staging_path=staging, validator=FoundationSchemaValidator(), one_page_quality=object(), m10_quality=_quality())
    assert not (staging / "quality_report.md").exists()


def test_m10_quality_rejects_count_drift_and_nonempty_tombstones(tmp_path):
    staging = tmp_path / "staging"; _write(staging)
    bad = copy.deepcopy(_quality()); bad.expected_counts["documents"] = 2
    with pytest.raises(M10QualityCompletionError): _complete(staging, quality=bad)
    assert not (staging / "quality_report.md").exists()
    staging2 = tmp_path / "staging2"
    # Writer schema-validates tombstones; an empty initial stream is the only accepted M10-C case.
    _write(staging2, tombstones=[])
    (staging2 / "tombstones.jsonl").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
    with pytest.raises(M10QualityCompletionError): _complete(staging2)
    assert not (staging2 / "quality_report.md").exists()


def test_m10_quality_rejects_duplicate_json_and_quality_mutation(tmp_path):
    staging = tmp_path / "staging"; _write(staging)
    (staging / "manifest.json").write_text('{"schema_version":"1.0","schema_version":"1.0"}\n', encoding="utf-8")
    with pytest.raises(M10QualityCompletionError): _complete(staging)
    assert not (staging / "quality_report.md").exists()

    staging2 = tmp_path / "staging2"; _write(staging2)
    quality = _quality(); before = copy.deepcopy(quality)
    _complete(staging2, quality=quality)
    assert quality == before


def test_m10_quality_preserves_preexisting_report(tmp_path):
    staging = tmp_path / "staging"; _write(staging)
    report = staging / "quality_report.md"; report.write_text("sentinel", encoding="utf-8")
    with pytest.raises(M10QualityCompletionError): _complete(staging)
    assert report.read_text(encoding="utf-8") == "sentinel"


@pytest.mark.parametrize("unsafe", [r"C:\\secrets\\embedding.yaml", "/etc/secret", "https://evil.example/secret"])
def test_m10_quality_rejects_unsafe_profile_identifiers(tmp_path, unsafe):
    staging = tmp_path / "staging"; _write(staging)
    quality = replace(_quality(), active_profile=unsafe)
    with pytest.raises(M10QualityCompletionError): _complete(staging, quality=quality)
    assert not (staging / "quality_report.md").exists()


class _SideEffectPath:
    def __init__(self, marker: Path):
        self.marker = marker

    def exists(self):
        self.marker.write_text("touched", encoding="utf-8")
        return False


@pytest.mark.parametrize("bad_kind", ["object", "none", "side_effect"])
def test_m10_quality_rejects_wrong_path_types_before_side_effects(tmp_path, bad_kind):
    marker = tmp_path / "marker"
    bad_path = {"object": object(), "none": None, "side_effect": _SideEffectPath(marker)}[bad_kind]
    with pytest.raises(M10QualityCompletionError):
        FullSnapshotStagingCompleter.complete(
            staging_path=bad_path,
            validator=FoundationSchemaValidator(),
            m10_quality=_quality(),
        )
    assert not marker.exists()


@pytest.mark.parametrize("blank", ["\n", "\n\n"])
def test_m10_quality_rejects_blank_jsonl_lines(tmp_path, blank):
    staging = tmp_path / "staging"; _write(staging)
    documents = staging / "documents.jsonl"
    documents.write_text(documents.read_text(encoding="utf-8") + blank, encoding="utf-8")
    with pytest.raises(M10QualityCompletionError): _complete(staging)
    assert not (staging / "quality_report.md").exists()
