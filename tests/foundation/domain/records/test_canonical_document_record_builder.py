from __future__ import annotations

import copy

import pytest

from knowledgenexus.foundation.domain.records import CanonicalDocumentRecordBuilder
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules import ContentHasher
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


SCHEMA_FIELDS = {
    "schema_version",
    "document_id",
    "source_system",
    "source_type",
    "title",
    "space_key",
    "page_id",
    "repo",
    "branch",
    "file_path",
    "url",
    "author",
    "source_version",
    "content_hash",
    "acl_id",
    "jira_keys",
    "relation_ids",
    "created_at",
    "updated_at",
    "crawled_at",
    "metadata",
}


def build_valid_record(
    *,
    normalized_body_text: str = "SVMC Root\n\nA normalized canonical document.",
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=normalized_body_text,
        acl_id="acl:confluence:page:938880621",
        crawled_at="2026-07-10T00:00:00Z",
        title="SVMC Root",
        space_key="SVMC",
        page_id="938880621",
        url="https://confluence.example/pages/938880621",
        author="spen",
        source_version="42",
        updated_at="2026-07-09T00:00:00Z",
        metadata=metadata,
    )


def test_builder_returns_dict() -> None:
    assert isinstance(build_valid_record(), dict)


def test_record_has_schema_version_1_0() -> None:
    assert build_valid_record()["schema_version"] == SCHEMA_VERSION


def test_content_hash_matches_normalized_body_text_hash() -> None:
    normalized_body_text = "Already normalized\n\nBody text"

    assert build_valid_record(normalized_body_text=normalized_body_text)[
        "content_hash"
    ] == ContentHasher.hash_text(normalized_body_text)


def test_empty_normalized_body_text_is_allowed() -> None:
    record = build_valid_record(normalized_body_text="")

    assert record["content_hash"] == ContentHasher.hash_text("")
    FoundationSchemaValidator().validate_record("CanonicalDocument", record)
    assert "normalized_body_text" not in record


def test_metadata_defaults_to_empty_dict() -> None:
    assert build_valid_record()["metadata"] == {}


def test_valid_built_record_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record("CanonicalDocument", build_valid_record())


def test_unknown_top_level_fields_are_not_added() -> None:
    assert set(build_valid_record()) == SCHEMA_FIELDS


def test_builder_does_not_mutate_metadata_input() -> None:
    metadata = {"source": "unit-test", "nested": {"kept": True}}
    original = copy.deepcopy(metadata)
    record = build_valid_record(metadata=metadata)

    assert metadata == original
    assert record["metadata"] == metadata
    assert record["metadata"] is not metadata


def test_builder_does_not_alias_list_inputs() -> None:
    jira_keys = ["SVMCSPEN-1234"]
    relation_ids = ["rel:0123456789abcdef"]
    record = CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:938880621",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text="Body",
        acl_id="acl:confluence:page:938880621",
        crawled_at="2026-07-10T00:00:00Z",
        jira_keys=jira_keys,
        relation_ids=relation_ids,
    )

    jira_keys.append("SVMCSPEN-9999")
    relation_ids.append("rel:fedcba9876543210")

    assert record["jira_keys"] == ["SVMCSPEN-1234"]
    assert record["jira_keys"] is not jira_keys
    assert record["relation_ids"] == ["rel:0123456789abcdef"]
    assert record["relation_ids"] is not relation_ids


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("document_id", 123, TypeError),
        ("document_id", "", ValueError),
        ("source_system", 123, TypeError),
        ("source_system", "", ValueError),
        ("source_type", 123, TypeError),
        ("source_type", "", ValueError),
        ("normalized_body_text", 123, TypeError),
        ("acl_id", 123, TypeError),
        ("acl_id", "", ValueError),
        ("crawled_at", 123, TypeError),
        ("crawled_at", "", ValueError),
    ],
)
def test_invalid_required_string_input_fails(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    kwargs = {
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "source_type": "wiki_page",
        "normalized_body_text": "Body",
        "acl_id": "acl:confluence:page:938880621",
        "crawled_at": "2026-07-10T00:00:00Z",
    }
    kwargs[field_name] = value

    with pytest.raises(error_type, match=field_name):
        CanonicalDocumentRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["jira_keys", "relation_ids"])
def test_invalid_list_input_fails(field_name: str) -> None:
    kwargs = {
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "source_type": "wiki_page",
        "normalized_body_text": "Body",
        "acl_id": "acl:confluence:page:938880621",
        "crawled_at": "2026-07-10T00:00:00Z",
        field_name: "not-a-list",
    }

    with pytest.raises(TypeError, match=f"{field_name} expects list"):
        CanonicalDocumentRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


def test_invalid_metadata_input_fails() -> None:
    with pytest.raises(TypeError, match="metadata expects dict"):
        CanonicalDocumentRecordBuilder.build(
            document_id="confluence:page:938880621",
            source_system="confluence",
            source_type="wiki_page",
            normalized_body_text="Body",
            acl_id="acl:confluence:page:938880621",
            crawled_at="2026-07-10T00:00:00Z",
            metadata=[],  # type: ignore[arg-type]
        )
