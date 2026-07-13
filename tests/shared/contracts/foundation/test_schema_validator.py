from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledgenexus.shared.contracts.foundation.contract_loader import (
    load_foundation_contract_schemas,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)


def valid_chunk_record() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "chunk_id": "chunk:confluence:0123456789abcdef",
        "document_id": "doc:confluence:938880621",
        "source_system": "confluence",
        "source_type": "wiki_page",
        "title": "SVMC Root",
        "text": "SVMC breadcrumb\n\nA valid chunk body.",
        "content_kind": "prose",
        "language": "en",
        "token_count": 8,
        "heading_path": ["SVMC", "Root"],
        "space_key": "SVMC",
        "page_id": "938880621",
        "repo": None,
        "branch": None,
        "file_path": None,
        "symbol": None,
        "line_start": None,
        "line_end": None,
        "part_index": None,
        "part_total": None,
        "jira_keys": [],
        "relation_ids": [],
        "acl_tags": ["space:SVMC"],
        "source_version": "42",
        "content_hash": "0" * 64,
        "chunker_version": "1.2.0",
        "updated_at": "2026-07-08T00:00:00Z",
    }


def valid_manifest_record(
    *,
    generated_at: str = "2026-07-13T09:30:15Z",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_version": "v20260713-023015-000000Z",
        "export_mode": "full_snapshot",
        "generated_at": generated_at,
        "config_hash": "0" * 64,
        "chunker_version": "1.2.0",
        "schemas_version": "foundation-schemas-1",
        "counts": {
            "documents": 1,
            "chunks": 1,
        },
    }


def valid_relation_record(
    *,
    created_at: str = "2026-07-13T09:30:15Z",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "relation_id": "rel:0123456789abcdef",
        "source_id": "doc:confluence:938880621",
        "target_id": "jira:issue:SPEN-1234",
        "relation_type": "mentions_jira_key",
        "resolution_status": "unresolved_without_jira_api",
        "created_at": created_at,
    }


def test_loader_can_load_all_contract_schemas() -> None:
    contract = load_foundation_contract_schemas()
    schema_files = sorted(contract.schema_dir.glob("*.json"))
    schema_ids = {
        schema_id
        for schema_path in schema_files
        if (schema_id := json.loads(schema_path.read_text(encoding="utf-8")).get("$id"))
    }

    assert contract.schema_dir == (
        Path.cwd() / "contracts" / "foundation" / "schemas"
    ).resolve()
    assert set(contract.schemas_by_id) == schema_ids
    assert "ChunkRecord" in contract.schemas_by_name
    assert (
        "https://svmc.samsung/knowledge/schemas/defs.schema.json"
        in contract.schemas_by_id
    )


def test_valid_chunk_record_passes() -> None:
    record = valid_chunk_record()
    original = copy.deepcopy(record)

    FoundationSchemaValidator().validate_record("ChunkRecord", record)

    assert record == original


def test_chunk_record_missing_acl_tags_fails() -> None:
    record = valid_chunk_record()
    del record["acl_tags"]

    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_record("ChunkRecord", record)

    message = str(raised.value)
    assert "ChunkRecord" in message
    assert "acl_tags" in message
    assert "path: <root>" in message


def test_chunk_record_with_unknown_top_level_field_fails() -> None:
    record = valid_chunk_record()
    record["unexpected"] = True

    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_record("ChunkRecord", record)

    message = str(raised.value)
    assert "Additional properties are not allowed" in message
    assert "unexpected" in message
    assert "path: <root>" in message


def test_invalid_jsonl_line_fails_with_line_number(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "chunks.jsonl"
    jsonl_path.write_text(
        json.dumps(valid_chunk_record()) + "\n" + "{not-json}\n",
        encoding="utf-8",
    )

    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_jsonl_file("ChunkRecord", jsonl_path)

    message = str(raised.value)
    assert "line 2" in message
    assert "Invalid JSON" in message
    assert str(jsonl_path) in message


def test_valid_jsonl_file_returns_record_count(tmp_path: Path) -> None:
    first_record = valid_chunk_record()
    second_record = valid_chunk_record()
    second_record["chunk_id"] = "chunk:confluence:fedcba9876543210"

    jsonl_path = tmp_path / "chunks.jsonl"
    jsonl_path.write_text(
        json.dumps(first_record) + "\n" + json.dumps(second_record) + "\n",
        encoding="utf-8",
    )

    count = FoundationSchemaValidator().validate_jsonl_file("ChunkRecord", jsonl_path)

    assert count == 2


@pytest.mark.parametrize(
    "generated_at",
    [
        "2026-07-13T09:30:15Z",
        "2026-07-13T09:30:15+05:30",
        "2026-07-13t09:30:15z",
    ],
)
def test_valid_manifest_date_time_passes(generated_at: str) -> None:
    FoundationSchemaValidator().validate_record(
        "Manifest",
        valid_manifest_record(generated_at=generated_at),
    )


def test_valid_manifest_fractional_seconds_date_time_passes() -> None:
    FoundationSchemaValidator().validate_record(
        "Manifest",
        valid_manifest_record(generated_at="2026-07-13T09:30:15.123456Z"),
    )


@pytest.mark.parametrize(
    "generated_at",
    [
        "not-a-date",
        "2026-07-13",
        "2026-13-40T25:61:61Z",
        "2026-07-13T09:30:15+00:60",
        "2026-07-13T09:30:15+05:99",
    ],
)
def test_manifest_invalid_date_time_format_fails(generated_at: str) -> None:
    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_record(
            "Manifest",
            valid_manifest_record(generated_at=generated_at),
        )

    assert raised.value.error_path == "generated_at"


def test_jsonl_file_rejects_invalid_manifest_date_time(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "manifest.jsonl"
    jsonl_path.write_text(
        json.dumps(valid_manifest_record(generated_at="not-a-date")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_jsonl_file("Manifest", jsonl_path)

    assert raised.value.error_path == "generated_at"
    assert raised.value.line_number == 1


def test_relation_date_time_format_is_enforced() -> None:
    with pytest.raises(FoundationValidationError) as raised:
        FoundationSchemaValidator().validate_record(
            "RelationRecord",
            valid_relation_record(created_at="2026-07-13"),
        )

    assert raised.value.error_path == "created_at"
