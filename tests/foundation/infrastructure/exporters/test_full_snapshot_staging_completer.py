from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from knowledgenexus.foundation.infrastructure.exporters import (
    FullSnapshotStagingCompleter,
    FullSnapshotStagingWriter,
)
from knowledgenexus.foundation.infrastructure.exporters import (
    full_snapshot_staging_completer as completer_module,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    JiraRelationQualityObservation,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import (
    EXPECTED_MACHINE_FILES,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)
from tests.fixtures.foundation.one_page_export_snapshot_fixtures import (
    build_quality_report_input,
)
from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)


VALID_DATASET_VERSION = "v20260713-093015-123456Z"
VALID_GENERATED_AT = "2026-07-13T09:30:15Z"
VALID_CONFIG_HASH = "a" * 64
VALID_CHUNKER_VERSION = "1.3.0"
VALID_SCHEMAS_VERSION = "1.0"
EXPECTED_COMPLETE_FILES = EXPECTED_MACHINE_FILES | {"quality_report.md"}
EXPECTED_COUNTS = {
    "documents": 1,
    "chunks": 1,
    "relations": 1,
    "acl": 1,
    "media_assets": 0,
    "symbols": 0,
    "sync_state": 0,
    "tombstones": 0,
}
EXPECTED_REPORT = (
    "# Foundation Export Quality Report\n"
    "\n"
    "## Snapshot\n"
    "\n"
    "- Dataset version: `v20260713-093015-123456Z`\n"
    "- Export mode: `full_snapshot`\n"
    "- Generated at: `2026-07-13T09:30:15Z`\n"
    "- Manifest schema version: `1.0`\n"
    "- Schemas version: `1.0`\n"
    "- Chunker version: `1.3.0`\n"
    f"- Config hash: `{'a' * 64}`\n"
    "\n"
    "## Record Counts\n"
    "\n"
    "| Record type | Count |\n"
    "|---|---:|\n"
    "| documents | 1 |\n"
    "| chunks | 1 |\n"
    "| relations | 1 |\n"
    "| acl | 1 |\n"
    "| media_assets | 0 |\n"
    "| symbols | 0 |\n"
    "| sync_state | 0 |\n"
    "| tombstones | 0 |\n"
    "\n"
    "## Completion Checks\n"
    "\n"
    "- Machine-readable staging file set: PASS\n"
    "- Manifest JSON parsing: PASS\n"
    "- Manifest schema validation: PASS\n"
    "- Full-snapshot producer invariants: PASS\n"
    "\n"
    "## Scope\n"
    "\n"
    "This report summarizes Foundation export construction metadata only.\n"
    "\n"
    "It does not evaluate retrieval, embedding, indexing, semantic quality,\n"
    "hallucination, or answer quality.\n"
).encode("utf-8")


def test_successfully_completes_existing_m3d_staging(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    expected_manifest = _write_machine_staging(staging_path)

    manifest = FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
    )

    assert manifest == expected_manifest
    assert manifest == _read_manifest(staging_path)
    assert _entry_names(staging_path) == EXPECTED_COMPLETE_FILES
    assert not (tmp_path / "LATEST.txt").exists()
    assert not (staging_path / "LATEST.txt").exists()
    assert not (tmp_path / VALID_DATASET_VERSION).exists()


def test_quality_report_has_exact_deterministic_bytes(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete(staging_path)

    assert (staging_path / "quality_report.md").read_bytes() == EXPECTED_REPORT
    assert EXPECTED_REPORT.endswith(b"\n")
    assert not EXPECTED_REPORT.endswith(b"\n\n")


def test_identical_manifests_produce_identical_reports(tmp_path: Path) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    _write_machine_staging(first_path)
    _write_machine_staging(second_path)

    _complete(first_path)
    _complete(second_path)

    assert (first_path / "quality_report.md").read_bytes() == (
        second_path / "quality_report.md"
    ).read_bytes()


def test_empty_stream_counts_are_all_rendered_as_zero(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path, empty=True)

    _complete(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    for count_key in EXPECTED_COUNTS:
        assert f"| {count_key} | 0 |" in report


def test_manifest_metadata_is_preserved_exactly(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(
        staging_path,
        dataset_version="v20260714-010203-040506Z",
        generated_at="2026-07-14T01:02:03Z",
        config_hash="b" * 64,
        chunker_version="9.8.7",
        schemas_version="schemas-test",
    )

    _complete(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    assert "- Dataset version: `v20260714-010203-040506Z`" in report
    assert "- Generated at: `2026-07-14T01:02:03Z`" in report
    assert "- Manifest schema version: `1.0`" in report
    assert "- Schemas version: `schemas-test`" in report
    assert "- Chunker version: `9.8.7`" in report
    assert f"- Config hash: `{'b' * 64}`" in report


@pytest.mark.parametrize(
    "source_scopes",
    [None, {"confluence": {"space_keys": ["SVMC"]}}],
)
def test_source_scopes_is_optional_and_not_rendered(
    tmp_path: Path,
    source_scopes: dict[str, object] | None,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path, source_scopes=source_scopes)

    _complete(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    assert "source_scopes" not in report
    assert "SVMC" not in report


def test_missing_machine_file_fails_without_modifying_remaining_files(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    (staging_path / "chunks.jsonl").unlink()
    before = _machine_file_bytes(staging_path)

    with pytest.raises(RuntimeError, match="unexpected entries"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()
    assert _machine_file_bytes(staging_path) == before


def test_unexpected_regular_file_is_rejected_and_preserved(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    unexpected = staging_path / "unexpected.txt"
    unexpected.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected entries"):
        _complete(staging_path)

    assert unexpected.read_text(encoding="utf-8") == "keep"
    assert not (staging_path / "quality_report.md").exists()


def test_unexpected_directory_is_rejected_and_preserved(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    unexpected = staging_path / "unexpected-dir"
    unexpected.mkdir()

    with pytest.raises(RuntimeError, match="unexpected entries"):
        _complete(staging_path)

    assert unexpected.is_dir()
    assert not (staging_path / "quality_report.md").exists()


def test_symlink_machine_entry_is_rejected_when_supported(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    target = tmp_path / "outside-documents.jsonl"
    target.write_bytes((staging_path / "documents.jsonl").read_bytes())
    link = staging_path / "documents.jsonl"
    link.unlink()
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(RuntimeError, match="unexpected entries"):
        _complete(staging_path)

    assert link.is_symlink()
    assert not (staging_path / "quality_report.md").exists()


def test_pre_existing_quality_report_is_not_overwritten(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    report_path = staging_path / "quality_report.md"
    report_path.write_text("sentinel", encoding="utf-8")
    before = _machine_file_bytes(staging_path)

    with pytest.raises(FileExistsError, match="already exists"):
        _complete(staging_path)

    assert report_path.read_text(encoding="utf-8") == "sentinel"
    assert _machine_file_bytes(staging_path) == before


def test_invalid_json_manifest_propagates_without_creating_report(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    (staging_path / "manifest.json").write_text("{invalid", encoding="utf-8")
    jsonl_before = _jsonl_file_bytes(staging_path)

    with pytest.raises(json.JSONDecodeError):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()
    assert _jsonl_file_bytes(staging_path) == jsonl_before


@pytest.mark.parametrize("manifest_value", [[], "manifest"])
def test_non_object_manifest_is_rejected(
    tmp_path: Path,
    manifest_value: object,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    _write_manifest_value(staging_path, manifest_value)

    with pytest.raises(TypeError, match="one object"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()


def test_manifest_schema_validation_failure_propagates(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    _mutate_manifest(
        staging_path,
        lambda manifest: manifest.__setitem__("generated_at", "not-a-date-time"),
    )

    with pytest.raises(FoundationValidationError):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()


def test_delta_manifest_is_rejected_by_full_snapshot_invariant(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    def make_delta(manifest: dict[str, object]) -> None:
        manifest["export_mode"] = "delta"
        manifest["base_dataset_version"] = "v20260712-000000-000000Z"

    _mutate_manifest(staging_path, make_delta)

    with pytest.raises(ValueError, match="export_mode"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()


def test_full_snapshot_manifest_with_base_version_is_rejected(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    _mutate_manifest(
        staging_path,
        lambda manifest: manifest.__setitem__(
            "base_dataset_version",
            "v20260712-000000-000000Z",
        ),
    )

    with pytest.raises(ValueError, match="base_dataset_version"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()


@pytest.mark.parametrize("case", ["missing", "extra"])
def test_wrong_manifest_count_key_set_is_rejected(
    tmp_path: Path,
    case: str,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    def change_counts(manifest: dict[str, object]) -> None:
        counts = manifest["counts"]
        assert isinstance(counts, dict)
        if case == "missing":
            del counts["chunks"]
        else:
            counts["unexpected"] = 0

    _mutate_manifest(staging_path, change_counts)

    with pytest.raises(ValueError, match="exactly"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()


@pytest.mark.parametrize(
    ("invalid_value", "expected_error"),
    [(True, TypeError), (-1, ValueError)],
)
def test_invalid_count_values_are_rejected_by_producer_boundary(
    invalid_value: object,
    expected_error: type[Exception],
) -> None:
    manifest: dict[str, object] = {"export_mode": "full_snapshot"}
    counts: dict[str, object] = dict(EXPECTED_COUNTS)
    counts["documents"] = invalid_value
    manifest["counts"] = counts

    with pytest.raises(expected_error):
        completer_module._verify_full_snapshot_invariants(manifest)


def test_report_link_failure_cleans_only_m3e_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    before = _machine_file_bytes(staging_path)
    original_link = completer_module.os.link

    def fail_report_link(src: object, dst: object) -> None:
        if Path(dst).name == "quality_report.md":
            raise OSError("forced report link failure")
        original_link(src, dst)

    monkeypatch.setattr(completer_module.os, "link", fail_report_link)

    with pytest.raises(OSError, match="forced report link failure"):
        _complete(staging_path)

    assert _entry_names(staging_path) == EXPECTED_MACHINE_FILES
    assert _machine_file_bytes(staging_path) == before


def test_final_verification_failure_removes_only_new_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    before = _machine_file_bytes(staging_path)
    original_write_report = completer_module._write_quality_report
    unexpected = staging_path / "unexpected.txt"

    def write_report_and_add_unexpected(path: Path, report: str) -> None:
        original_write_report(path, report)
        unexpected.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        completer_module,
        "_write_quality_report",
        write_report_and_add_unexpected,
    )

    with pytest.raises(RuntimeError, match="unexpected entries"):
        _complete(staging_path)

    assert not (staging_path / "quality_report.md").exists()
    assert unexpected.read_text(encoding="utf-8") == "keep"
    assert _machine_file_bytes(staging_path) == before


def test_completion_does_not_publish_move_or_delete_staging(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete(staging_path)

    assert staging_path.is_dir()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["staging"]
    assert not (tmp_path / "LATEST.txt").exists()
    assert not (tmp_path / VALID_DATASET_VERSION).exists()


def test_missing_or_non_directory_staging_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _complete(tmp_path / "missing")

    file_path = tmp_path / "staging-file"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        _complete(file_path)


def _write_machine_staging(
    staging_path: Path,
    *,
    empty: bool = False,
    dataset_version: str = VALID_DATASET_VERSION,
    generated_at: str = VALID_GENERATED_AT,
    config_hash: str = VALID_CONFIG_HASH,
    chunker_version: str = VALID_CHUNKER_VERSION,
    schemas_version: str = VALID_SCHEMAS_VERSION,
    source_scopes: dict[str, object] | None = None,
) -> dict[str, object]:
    records = [] if empty else [build_sample_document_record()]
    chunks = [] if empty else [build_sample_chunk_record()]
    relations = [] if empty else [build_sample_relation_record()]
    acl = [] if empty else [build_sample_acl_record()]
    return FullSnapshotStagingWriter.write(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
        dataset_version=dataset_version,
        generated_at=generated_at,
        config_hash=config_hash,
        chunker_version=chunker_version,
        schemas_version=schemas_version,
        documents=records,
        chunks=chunks,
        relations=relations,
        acl=acl,
        media_assets=[],
        symbols=[],
        sync_state=[],
        tombstones=[],
        source_scopes=source_scopes,
    )


def _complete(staging_path: Path) -> dict[str, object]:
    return FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
    )


def _read_manifest(staging_path: Path) -> dict[str, object]:
    manifest = json.loads(
        (staging_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(manifest, dict)
    return manifest


def _mutate_manifest(
    staging_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    manifest = copy.deepcopy(_read_manifest(staging_path))
    mutation(manifest)
    _write_manifest_value(staging_path, manifest)


def _write_manifest_value(staging_path: Path, value: object) -> None:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    (staging_path / "manifest.json").write_text(
        serialized + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _entry_names(path: Path) -> set[str]:
    return {entry.name for entry in path.iterdir()}


def _machine_file_bytes(staging_path: Path) -> dict[str, bytes]:
    return {
        name: (staging_path / name).read_bytes()
        for name in EXPECTED_MACHINE_FILES
        if (staging_path / name).is_file()
    }


def _jsonl_file_bytes(staging_path: Path) -> dict[str, bytes]:
    return {
        name: (staging_path / name).read_bytes()
        for name in EXPECTED_MACHINE_FILES
        if name.endswith(".jsonl")
    }


# --- extended path (M6G-C) ------------------------------------------------


def _complete_extended(staging_path: Path, **overrides: object) -> dict[str, object]:
    return FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
        one_page_quality=build_quality_report_input(**overrides),
    )


def test_legacy_call_shape_is_unaffected_by_extended_path_addition(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    # The exact two-keyword legacy call shape the golden fixture exercises.
    manifest = FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
    )

    assert manifest is not None
    assert (staging_path / "quality_report.md").read_bytes() == EXPECTED_REPORT


def test_extended_report_has_nine_sections_in_locked_order(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete_extended(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    section_order = [
        "## Snapshot",
        "## Active Profiles",
        "## Record Counts",
        "## Jira Relation Quality",
        "## ACL Quality",
        "## Empty and Deferred Streams",
        "## Completion Checks",
        "## Publication State",
        "## Scope",
    ]
    positions = [report.index(section) for section in section_order]
    assert positions == sorted(positions)
    assert report.endswith("\n")
    assert not report.endswith("\n\n")


def test_extended_report_field_content(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete_extended(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    assert "- Active profile: `medium`" in report
    assert "- Profile status: `provisional_until_benchmark`" in report
    assert "- Chunker version: `1.0.0`" in report
    assert "media_assets: empty; deferred" in report
    assert "symbols: empty; deferred" in report
    assert "sync_state: empty; checkpoint persistence deferred to M7" in report
    assert "tombstones: empty; delta/deletion production deferred" in report
    assert "- Final-directory verification: PENDING_AT_REPORT_COMPLETION" in report
    assert "- LATEST.txt verification: PENDING_AT_REPORT_COMPLETION" in report
    assert "- Post-publication acceptance: PENDING_AT_REPORT_COMPLETION" in report
    assert "- Manifest counts match emitted records: PASS" in report
    assert "- JSONL schema validation: PASS" in report
    assert "- Deferred streams are empty: PASS" in report
    assert "true" in report or "false" in report
    assert "- Default deny applied: false" in report
    assert "- Manual review required: false" in report
    # Snapshot section must not repeat chunker version (moved to Active Profiles).
    snapshot_section = report.split("## Active Profiles")[0]
    assert "Chunker version" not in snapshot_section


def test_extended_report_empty_jira_lists_render_none(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete_extended(
        staging_path,
        jira_quality_observation=JiraRelationQualityObservation(
            unique_key_like_candidates=(),
            allowlisted_keys=(),
            outside_allowlist_keys=(),
        ),
        jira_metrics={
            "candidate_occurrences": 0,
            "unique_key_like_count": 0,
            "allowlisted_unique_count": 0,
            "outside_allowlist_unique_count": 0,
            "duplicate_occurrences": 0,
            "relations_total": 1,
            "documents_enriched": 1,
            "chunks_enriched": 1,
        },
    )

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    jira_section = report.split("## Jira Relation Quality")[1].split("## ACL Quality")[0]
    assert jira_section.count("- None") == 3


def test_extended_report_never_leaks_acl_tags_or_principals(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete_extended(staging_path)

    report = (staging_path / "quality_report.md").read_text(encoding="utf-8")
    for forbidden in (
        "acl_tags",
        "allowed_users",
        "allowed_groups",
        "crawler_identity",
        "restriction_source_page_ids",
        "space:SVMC",
    ):
        assert forbidden not in report


def test_extended_path_rejects_expected_counts_mismatch(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    mismatched_counts = {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 1,
    }

    with pytest.raises(ValueError):
        _complete_extended(staging_path, expected_counts=mismatched_counts)

    assert not (staging_path / "quality_report.md").exists()


def test_extended_path_rejects_non_empty_deferred_stream(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    (staging_path / "media_assets.jsonl").write_text(
        json.dumps({"unexpected": True}) + "\n", encoding="utf-8"
    )
    counts = dict(_read_manifest(staging_path)["counts"])
    counts["media_assets"] = 1
    _write_manifest_value(
        staging_path,
        {**_read_manifest(staging_path), "counts": counts},
    )

    with pytest.raises(ValueError):
        _complete_extended(staging_path)

    assert not (staging_path / "quality_report.md").exists()


def test_extended_path_rejects_wrong_quality_input_type(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    with pytest.raises(TypeError):
        FullSnapshotStagingCompleter.complete(
            staging_path=staging_path,
            validator=FoundationSchemaValidator(),
            one_page_quality=object(),
        )


def test_extended_path_does_not_mutate_quality_input(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    quality_input = build_quality_report_input()
    before = copy.deepcopy(quality_input)

    FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
        one_page_quality=quality_input,
    )

    assert quality_input == before


# --- R12 TOCTOU hardening --------------------------------------------------


def test_r12_concurrent_creation_between_check_and_write_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)
    report_path = staging_path / "quality_report.md"
    winner_bytes = b"# winner wrote this first\n"

    original_link = completer_module.os.link

    def concurrent_writer_wins_the_race(src: object, dst: object) -> None:
        # Simulate a second process creating the report between this
        # process's existence pre-check and its own attempt to link the
        # report into place.
        report_path.write_bytes(winner_bytes)
        original_link(src, dst)

    monkeypatch.setattr(completer_module.os, "link", concurrent_writer_wins_the_race)

    with pytest.raises(FileExistsError):
        _complete(staging_path)

    assert report_path.read_bytes() == winner_bytes


def test_r12_hardening_preserves_legacy_byte_identical_output(
    tmp_path: Path,
) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
    )

    assert (staging_path / "quality_report.md").read_bytes() == EXPECTED_REPORT
    assert _entry_names(staging_path) == EXPECTED_COMPLETE_FILES


def test_r12_write_leaves_no_leftover_temp_file_on_success(tmp_path: Path) -> None:
    staging_path = tmp_path / "staging"
    _write_machine_staging(staging_path)

    _complete(staging_path)

    leftovers = [
        entry.name
        for entry in staging_path.iterdir()
        if entry.name.startswith(".quality_report.md.")
    ]
    assert leftovers == []
