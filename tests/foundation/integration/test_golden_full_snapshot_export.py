from __future__ import annotations

import json
from pathlib import Path

from knowledgenexus.foundation.domain.rules import ContentHasher, ChunkIdGenerator
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import (
    COUNT_KEYS,
    EXPECTED_COMPLETE_FILES,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import (
    JSONL_FILE_SCHEMA_PAIRS,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from tests.fixtures.foundation.golden_record_set import (
    GOLDEN_ACL_ID,
    GOLDEN_CODE_CHUNK_ID,
    GOLDEN_CODE_TEXT,
    GOLDEN_CODE_TOKEN_COUNT,
    GOLDEN_DATASET_VERSION,
    GOLDEN_DOCUMENT_ID,
    GOLDEN_GENERATED_AT,
    GOLDEN_MEDIA_ID,
    GOLDEN_PROSE_CHUNK_ID,
    GOLDEN_PROSE_TEXT,
    GOLDEN_PROSE_TOKEN_COUNT,
    GOLDEN_RELATION_ID,
    GOLDEN_SOURCE_SCOPES,
    generate_golden_full_snapshot,
)


GOLDEN_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "foundation"
    / "golden_full_snapshot"
)
EXPECTED_COUNTS = {
    "documents": 1,
    "chunks": 2,
    "relations": 1,
    "acl": 1,
    "media_assets": 1,
    "symbols": 0,
    "sync_state": 1,
    "tombstones": 0,
}


def test_generated_golden_snapshot_matches_committed_fixture(
    tmp_path: Path,
) -> None:
    generated_root = tmp_path / "golden-dataset"
    generated_root.mkdir()

    generate_golden_full_snapshot(generated_root)

    _assert_trees_match(GOLDEN_FIXTURE_ROOT, generated_root)


def test_committed_golden_snapshot_is_contract_valid() -> None:
    latest_path = GOLDEN_FIXTURE_ROOT / "LATEST.txt"
    assert latest_path.read_bytes() == (GOLDEN_DATASET_VERSION + "\n").encode()

    snapshot_path = GOLDEN_FIXTURE_ROOT / GOLDEN_DATASET_VERSION
    assert snapshot_path.is_dir()
    entries = list(snapshot_path.iterdir())
    assert {entry.name for entry in entries} == EXPECTED_COMPLETE_FILES
    assert all(entry.is_file() and not entry.is_symlink() for entry in entries)

    manifest = _read_object(snapshot_path / "manifest.json")
    FoundationSchemaValidator().validate_record("Manifest", manifest)
    assert snapshot_path.name == manifest["dataset_version"]
    assert manifest["dataset_version"] == GOLDEN_DATASET_VERSION
    assert manifest["export_mode"] == "full_snapshot"
    assert "base_dataset_version" not in manifest
    assert set(manifest["counts"]) == set(COUNT_KEYS)  # type: ignore[arg-type]
    assert manifest["counts"] == EXPECTED_COUNTS
    assert manifest["source_scopes"] == GOLDEN_SOURCE_SCOPES

    actual_counts: dict[str, int] = {}
    validator = FoundationSchemaValidator()
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        actual_counts[count_key] = _validate_jsonl_file(
            snapshot_path / file_name,
            schema_name=schema_name,
            validator=validator,
        )

    assert actual_counts == manifest["counts"]
    assert (snapshot_path / "symbols.jsonl").read_bytes() == b""
    assert (snapshot_path / "tombstones.jsonl").read_bytes() == b""

    report = (snapshot_path / "quality_report.md").read_text(encoding="utf-8")
    assert report.endswith("\n")
    assert not report.endswith("\n\n")
    assert f"- Dataset version: `{GOLDEN_DATASET_VERSION}`" in report
    assert f"- Generated at: `{GOLDEN_GENERATED_AT}`" in report
    for count_key, count in EXPECTED_COUNTS.items():
        assert f"| {count_key} | {count} |" in report
    assert "space_keys" not in report
    assert "page_ids" not in report
    assert "GOLDEN" not in report
    assert "Semantic quality: PASS" not in report
    assert "It does not evaluate retrieval" in report


def test_golden_snapshot_generation_is_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    generate_golden_full_snapshot(first_root)
    generate_golden_full_snapshot(second_root)

    _assert_trees_match(first_root, second_root)


def test_golden_graph_preserves_m2d_invariants() -> None:
    records = _read_committed_record_set()
    document_ids = _ids(records["documents"], "document_id")
    relation_ids = _ids(records["relations"], "relation_id")
    chunk_ids = _ids(records["chunks"], "chunk_id")
    acl_tags_by_document = {
        record["document_id"]: set(record["acl_tags"])  # type: ignore[arg-type]
        for record in records["acl"]
    }

    assert _ids(records["chunks"], "document_id") <= document_ids
    assert _ids(records["acl"], "document_id") <= document_ids
    assert _ids(records["media_assets"], "parent_document_id") <= document_ids
    assert _ids(records["sync_state"], "entity_id") <= document_ids
    assert _ids(records["relations"], "source_id") <= document_ids
    assert _ids(records["relations"], "target_id") == {"jira:issue:GOLDEN-1"}

    for chunk in records["chunks"]:
        assert set(chunk["relation_ids"]) <= relation_ids  # type: ignore[arg-type]
        assert set(chunk["acl_tags"]) <= acl_tags_by_document[  # type: ignore[arg-type]
            chunk["document_id"]
        ]

    assert document_ids == {GOLDEN_DOCUMENT_ID}
    assert chunk_ids == {GOLDEN_PROSE_CHUNK_ID, GOLDEN_CODE_CHUNK_ID}
    assert relation_ids == {GOLDEN_RELATION_ID}
    assert _ids(records["acl"], "acl_id") == {GOLDEN_ACL_ID}

    id_fields = {
        "documents": "document_id",
        "chunks": "chunk_id",
        "relations": "relation_id",
        "acl": "acl_id",
        "media_assets": "media_id",
        "sync_state": "entity_id",
    }
    for collection_name, id_field in id_fields.items():
        values = [record[id_field] for record in records[collection_name]]
        assert len(values) == len(set(values))


def test_exported_wiki_chunk_text_is_exact() -> None:
    records = _read_committed_record_set()
    chunks_by_id = {record["chunk_id"]: record for record in records["chunks"]}

    assert chunks_by_id[GOLDEN_PROSE_CHUNK_ID]["text"] == GOLDEN_PROSE_TEXT
    assert chunks_by_id[GOLDEN_CODE_CHUNK_ID]["text"] == GOLDEN_CODE_TEXT
    assert chunks_by_id[GOLDEN_PROSE_CHUNK_ID]["token_count"] == (
        GOLDEN_PROSE_TOKEN_COUNT
    )
    assert chunks_by_id[GOLDEN_CODE_CHUNK_ID]["token_count"] == (
        GOLDEN_CODE_TOKEN_COUNT
    )
    assert chunks_by_id[GOLDEN_PROSE_CHUNK_ID]["content_hash"] == (
        ContentHasher.hash_text(GOLDEN_PROSE_TEXT)
    )
    assert chunks_by_id[GOLDEN_CODE_CHUNK_ID]["content_hash"] == (
        ContentHasher.hash_text(GOLDEN_CODE_TEXT)
    )
    assert GOLDEN_PROSE_CHUNK_ID == ChunkIdGenerator.generate_chunk_id(
        "confluence",
        GOLDEN_DOCUMENT_ID,
        "Golden Foundation Sample › Overview",
        GOLDEN_PROSE_TEXT,
    )
    assert GOLDEN_CODE_CHUNK_ID == ChunkIdGenerator.generate_chunk_id(
        "confluence",
        GOLDEN_DOCUMENT_ID,
        "Golden Foundation Sample › Example Code#code0",
        GOLDEN_CODE_TEXT,
    )
    assert GOLDEN_CODE_TEXT.endswith(
        "```cpp\nint golden_value() { return 42; }\n```"
    )


def test_exported_symbols_stream_is_empty() -> None:
    snapshot_path = GOLDEN_FIXTURE_ROOT / GOLDEN_DATASET_VERSION
    manifest = _read_object(snapshot_path / "manifest.json")

    assert (snapshot_path / "symbols.jsonl").read_bytes() == b""
    assert manifest["counts"]["symbols"] == 0  # type: ignore[index]


def test_exported_media_id_uses_attachment_identity_convention() -> None:
    records = _read_committed_record_set()

    assert _ids(records["media_assets"], "media_id") == {GOLDEN_MEDIA_ID}
    assert GOLDEN_MEDIA_ID == "confluence:attachment:golden-media-001"


def _assert_trees_match(expected_root: Path, actual_root: Path) -> None:
    expected_entries = _relative_entries(expected_root)
    actual_entries = _relative_entries(actual_root)
    missing = sorted(expected_entries.keys() - actual_entries.keys())
    unexpected = sorted(actual_entries.keys() - expected_entries.keys())
    wrong_kinds = sorted(
        path
        for path in expected_entries.keys() & actual_entries.keys()
        if expected_entries[path] != actual_entries[path]
    )

    expected_files = _relative_file_bytes(expected_root)
    actual_files = _relative_file_bytes(actual_root)
    byte_different = sorted(
        path
        for path in expected_files.keys() & actual_files.keys()
        if expected_files[path] != actual_files[path]
    )

    assert not (missing or unexpected or wrong_kinds or byte_different), (
        f"missing={missing}, unexpected={unexpected}, "
        f"wrong_kinds={wrong_kinds}, byte_different={byte_different}"
    )


def _relative_entries(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): "directory" if path.is_dir() else "file"
        for path in root.rglob("*")
    }


def _relative_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _read_committed_record_set() -> dict[str, list[dict[str, object]]]:
    snapshot_path = GOLDEN_FIXTURE_ROOT / GOLDEN_DATASET_VERSION
    records: dict[str, list[dict[str, object]]] = {}

    for file_name, count_key, _ in JSONL_FILE_SCHEMA_PAIRS:
        records[count_key] = _read_jsonl_records(snapshot_path / file_name)

    return records


def _read_jsonl_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(raw_line)
        assert isinstance(record, dict)
        records.append(record)
    return records


def _validate_jsonl_file(
    path: Path,
    *,
    schema_name: str,
    validator: FoundationSchemaValidator,
) -> int:
    raw_bytes = path.read_bytes()
    if not raw_bytes:
        return 0

    assert raw_bytes.endswith(b"\n")
    assert not raw_bytes.endswith(b"\n\n")
    raw_lines = raw_bytes.splitlines()
    assert all(raw_line for raw_line in raw_lines)

    for raw_line in raw_lines:
        record = json.loads(raw_line)
        assert isinstance(record, dict)
        validator.validate_record(schema_name, record)

    return len(raw_lines)


def _ids(records: list[dict[str, object]], field_name: str) -> set[object]:
    return {record[field_name] for record in records}
