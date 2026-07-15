from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.records import ChunkRecordBuilder
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules import ContentHasher
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


def build_valid_confluence_record(
    *,
    text: str = "SVMC Root\n\nAlready normalized chunk text.",
) -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id="chunk:confluence:0123456789abcdef",
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        text=text,
        content_kind="prose",
        language="en",
        token_count=7,
        acl_tags=["space:SVMC"],
        chunker_version="1.0.0",
        title="SVMC Root",
        heading_path=["SVMC Root", "Overview"],
        space_key="SVMC",
        page_id="938880621",
        jira_keys=["SVMCSPEN-1234"],
        relation_ids=["rel:0123456789abcdef"],
        source_version="42",
        updated_at="2026-07-10T00:00:00Z",
    )


def build_valid_git_record() -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id="chunk:git:fedcba9876543210",
        document_id="git:file:spen-sdk:src/main.py",
        source_system="git",
        source_type="code_file",
        text="def build() -> None:\n    pass\n",
        content_kind="code_symbol",
        language="python",
        token_count=8,
        acl_tags=["repo:spen-sdk"],
        chunker_version="1.0.0",
        repo="spen-sdk",
        branch="main",
        file_path="src/main.py",
        symbol="build",
        line_start=10,
        line_end=11,
        part_index=0,
        part_total=1,
        source_version="0123456789abcdef0123456789abcdef01234567",
    )


def test_builder_returns_dict() -> None:
    assert isinstance(build_valid_confluence_record(), dict)


def test_record_has_schema_version_1_0() -> None:
    assert build_valid_confluence_record()["schema_version"] == SCHEMA_VERSION


def test_content_hash_matches_text_hash() -> None:
    text = "Already normalized\n\nChunk text"

    assert build_valid_confluence_record(text=text)[
        "content_hash"
    ] == ContentHasher.hash_text(text)


def test_valid_confluence_prose_record_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record(
        "ChunkRecord",
        build_valid_confluence_record(),
    )


def test_valid_git_code_record_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record("ChunkRecord", build_valid_git_record())


def test_jira_keys_and_relation_ids_default_to_empty_lists() -> None:
    record = ChunkRecordBuilder.build(
        chunk_id="chunk:confluence:0123456789abcdef",
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        text="Chunk text",
        content_kind="prose",
        language="en",
        token_count=2,
        acl_tags=["space:SVMC"],
        chunker_version="1.0.0",
    )

    assert record["jira_keys"] == []
    assert record["relation_ids"] == []
    FoundationSchemaValidator().validate_record("ChunkRecord", record)


def test_optional_fields_are_omitted_when_absent_except_default_lists() -> None:
    record = ChunkRecordBuilder.build(
        chunk_id="chunk:confluence:0123456789abcdef",
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        text="Chunk text",
        content_kind="prose",
        language="en",
        token_count=2,
        acl_tags=["space:SVMC"],
        chunker_version="1.0.0",
    )

    assert "title" not in record
    assert "heading_path" not in record
    assert "updated_at" not in record
    assert record["jira_keys"] == []
    assert record["relation_ids"] == []


def test_input_lists_are_copied_not_mutated_or_shared() -> None:
    heading_path = ["Root", "Leaf"]
    acl_tags = ["space:SVMC"]
    jira_keys = ["SVMCSPEN-1234"]
    relation_ids = ["rel:0123456789abcdef"]

    record = ChunkRecordBuilder.build(
        chunk_id="chunk:confluence:0123456789abcdef",
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        text="Chunk text",
        content_kind="prose",
        language="en",
        token_count=2,
        heading_path=heading_path,
        acl_tags=acl_tags,
        chunker_version="1.0.0",
        jira_keys=jira_keys,
        relation_ids=relation_ids,
    )

    heading_path.append("Mutated")
    acl_tags.append("space:OTHER")
    jira_keys.append("SVMCSPEN-9999")
    relation_ids.append("rel:fedcba9876543210")

    assert record["heading_path"] == ["Root", "Leaf"]
    assert record["heading_path"] is not heading_path
    assert record["acl_tags"] == ["space:SVMC"]
    assert record["acl_tags"] is not acl_tags
    assert record["jira_keys"] == ["SVMCSPEN-1234"]
    assert record["jira_keys"] is not jira_keys
    assert record["relation_ids"] == ["rel:0123456789abcdef"]
    assert record["relation_ids"] is not relation_ids


def test_acl_tags_empty_fails() -> None:
    with pytest.raises(ValueError, match="acl_tags"):
        ChunkRecordBuilder.build(
            chunk_id="chunk:confluence:0123456789abcdef",
            document_id="confluence:page:938880621",
            source_system="confluence",
            source_type="wiki_page",
            text="Chunk text",
            content_kind="prose",
            language="en",
            token_count=2,
            acl_tags=[],
            chunker_version="1.0.0",
        )


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("chunk_id", 123, TypeError),
        ("chunk_id", "", ValueError),
        ("document_id", 123, TypeError),
        ("document_id", "", ValueError),
        ("source_system", 123, TypeError),
        ("source_system", "", ValueError),
        ("source_type", 123, TypeError),
        ("source_type", "", ValueError),
        ("text", 123, TypeError),
        ("text", "", ValueError),
        ("content_kind", 123, TypeError),
        ("content_kind", "", ValueError),
        ("language", 123, TypeError),
        ("language", "", ValueError),
        ("chunker_version", 123, TypeError),
        ("chunker_version", "", ValueError),
    ],
)
def test_invalid_required_string_input_fails(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    kwargs = {
        "chunk_id": "chunk:confluence:0123456789abcdef",
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "source_type": "wiki_page",
        "text": "Chunk text",
        "content_kind": "prose",
        "language": "en",
        "token_count": 2,
        "acl_tags": ["space:SVMC"],
        "chunker_version": "1.0.0",
    }
    kwargs[field_name] = value

    with pytest.raises(error_type, match=field_name):
        ChunkRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("token_count", "error_type"),
    [
        ("2", TypeError),
        (True, TypeError),
        (-1, ValueError),
    ],
)
def test_invalid_token_count_fails(
    token_count: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type, match="token_count"):
        ChunkRecordBuilder.build(
            chunk_id="chunk:confluence:0123456789abcdef",
            document_id="confluence:page:938880621",
            source_system="confluence",
            source_type="wiki_page",
            text="Chunk text",
            content_kind="prose",
            language="en",
            token_count=token_count,  # type: ignore[arg-type]
            acl_tags=["space:SVMC"],
            chunker_version="1.0.0",
        )


@pytest.mark.parametrize(
    "field_name",
    ["heading_path", "acl_tags", "jira_keys", "relation_ids"],
)
def test_invalid_list_input_fails(field_name: str) -> None:
    kwargs = {
        "chunk_id": "chunk:confluence:0123456789abcdef",
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "source_type": "wiki_page",
        "text": "Chunk text",
        "content_kind": "prose",
        "language": "en",
        "token_count": 2,
        "acl_tags": ["space:SVMC"],
        "chunker_version": "1.0.0",
        field_name: "not-a-list",
    }

    with pytest.raises(TypeError, match=f"{field_name} expects list"):
        ChunkRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


def test_builder_does_not_normalize_or_alter_text() -> None:
    text = "Line with trailing spaces   \r\n\r\n\nNext line"
    record = build_valid_confluence_record(text=text)

    assert record["text"] == text
    assert record["content_hash"] == ContentHasher.hash_text(text)
