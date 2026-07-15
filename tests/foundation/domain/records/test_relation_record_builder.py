from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.records import RelationRecordBuilder
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


def build_valid_jira_record(
    *,
    evidence: str | None = "Mentioned as SVMCSPEN-1234 in the page body.",
    confidence: int | float | None = 1.0,
) -> dict[str, object]:
    return RelationRecordBuilder.build(
        relation_id="rel:0123456789abcdef",
        source_id="confluence:page:938880621",
        target_id="jira:issue:SVMCSPEN-1234",
        relation_type="mentions_jira_key",
        resolution_status="unresolved_without_jira_api",
        created_at="2026-07-10T00:00:00Z",
        evidence=evidence,
        confidence=confidence,
    )


def build_valid_non_jira_record() -> dict[str, object]:
    return RelationRecordBuilder.build(
        relation_id="rel:fedcba9876543210",
        source_id="confluence:page:938880621",
        target_id="confluence:page:938880622",
        relation_type="links_to_page",
        resolution_status="resolved",
        created_at="2026-07-10T00:00:00Z",
    )


def test_builder_returns_dict() -> None:
    assert isinstance(build_valid_jira_record(), dict)


def test_record_has_schema_version_1_0() -> None:
    assert build_valid_jira_record()["schema_version"] == SCHEMA_VERSION


def test_valid_jira_record_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record(
        "RelationRecord",
        build_valid_jira_record(),
    )


def test_valid_non_jira_record_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record(
        "RelationRecord",
        build_valid_non_jira_record(),
    )


def test_full_record_with_evidence_and_confidence_passes_schema_validation() -> None:
    record = build_valid_jira_record(
        evidence="Inline Jira mention in Confluence body.",
        confidence=0.75,
    )

    assert record["evidence"] == "Inline Jira mention in Confluence body."
    assert record["confidence"] == 0.75
    FoundationSchemaValidator().validate_record("RelationRecord", record)


def test_evidence_and_confidence_are_omitted_when_none() -> None:
    record = build_valid_jira_record(evidence=None, confidence=None)

    assert "evidence" not in record
    assert "confidence" not in record
    FoundationSchemaValidator().validate_record("RelationRecord", record)


def test_empty_evidence_string_is_allowed() -> None:
    record = build_valid_jira_record(evidence="", confidence=None)

    assert record["evidence"] == ""
    FoundationSchemaValidator().validate_record("RelationRecord", record)


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("relation_id", 123, TypeError),
        ("relation_id", "", ValueError),
        ("source_id", 123, TypeError),
        ("source_id", "", ValueError),
        ("target_id", 123, TypeError),
        ("target_id", "", ValueError),
        ("relation_type", 123, TypeError),
        ("relation_type", "", ValueError),
        ("resolution_status", 123, TypeError),
        ("resolution_status", "", ValueError),
        ("created_at", 123, TypeError),
        ("created_at", "", ValueError),
    ],
)
def test_invalid_required_string_input_fails(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    kwargs = {
        "relation_id": "rel:0123456789abcdef",
        "source_id": "confluence:page:938880621",
        "target_id": "jira:issue:SVMCSPEN-1234",
        "relation_type": "mentions_jira_key",
        "resolution_status": "unresolved_without_jira_api",
        "created_at": "2026-07-10T00:00:00Z",
    }
    kwargs[field_name] = value

    with pytest.raises(error_type, match=field_name):
        RelationRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


def test_invalid_evidence_type_fails() -> None:
    with pytest.raises(TypeError, match="evidence expects str"):
        build_valid_jira_record(evidence=123)  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", ["0.5", True, object()])
def test_invalid_confidence_type_fails(confidence: object) -> None:
    with pytest.raises(TypeError, match="confidence expects number"):
        build_valid_jira_record(confidence=confidence)  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", [0, 1, 0.5])
def test_integer_and_floating_point_confidence_values_are_accepted(
    confidence: int | float,
) -> None:
    record = build_valid_jira_record(confidence=confidence)

    assert record["confidence"] == confidence
    FoundationSchemaValidator().validate_record("RelationRecord", record)


@pytest.mark.parametrize(
    "confidence",
    [float("nan"), float("inf"), float("-inf"), -0.1, 1.1],
)
def test_invalid_confidence_value_fails(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        build_valid_jira_record(confidence=confidence)


def test_relation_id_matches_caller_provided_value() -> None:
    record = RelationRecordBuilder.build(
        relation_id="rel:1111111111111111",
        source_id="confluence:page:938880621",
        target_id="confluence:page:938880622",
        relation_type="links_to_page",
        resolution_status="resolved",
        created_at="2026-07-10T00:00:00Z",
    )

    assert record["relation_id"] == "rel:1111111111111111"


def test_schema_validation_proves_no_unknown_top_level_fields_are_added() -> None:
    FoundationSchemaValidator().validate_record(
        "RelationRecord",
        build_valid_jira_record(),
    )
