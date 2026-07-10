from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.records import ACLRecordBuilder
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)


def build_unrestricted_confluence_record(
    *,
    acl_tags: list[str] | None = None,
) -> dict[str, object]:
    return ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880621",
        document_id="confluence:page:938880621",
        source_system="confluence",
        is_restricted=False,
        acl_tags=acl_tags or ["space:SVMC"],
        acl_extraction_status="ok",
        extracted_at="2026-07-10T00:00:00Z",
    )


def build_restricted_confluence_record() -> dict[str, object]:
    return ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880622",
        document_id="confluence:page:938880622",
        source_system="confluence",
        is_restricted=True,
        acl_tags=["user:spen", "group:foundation-team"],
        acl_extraction_status="ok",
        extracted_at="2026-07-10T00:00:00Z",
        crawler_identity="svc-foundation-crawler",
        restriction_inherited=True,
        restriction_source_page_ids=["938880600"],
        allowed_users=["spen"],
        allowed_groups=["foundation-team"],
        acl_confidence="exact",
    )


def test_builder_returns_dict() -> None:
    assert isinstance(build_unrestricted_confluence_record(), dict)


def test_record_has_schema_version_1_0() -> None:
    assert build_unrestricted_confluence_record()["schema_version"] == SCHEMA_VERSION


def test_unrestricted_confluence_acl_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record(
        "ACLRecord",
        build_unrestricted_confluence_record(),
    )


def test_restricted_confluence_acl_passes_foundation_schema_validation() -> None:
    FoundationSchemaValidator().validate_record(
        "ACLRecord",
        build_restricted_confluence_record(),
    )


def test_unresolved_default_deny_acl_passes_foundation_schema_validation() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880623",
        document_id="confluence:page:938880623",
        source_system="confluence",
        is_restricted=True,
        acl_tags=["restricted:unresolved"],
        acl_extraction_status="unavailable",
        extracted_at="2026-07-10T00:00:00Z",
    )

    FoundationSchemaValidator().validate_record("ACLRecord", record)


def test_git_repository_acl_passes_foundation_schema_validation() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:git:file:spen-sdk:src/main.py",
        document_id="git:file:spen-sdk:src/main.py",
        source_system="git",
        is_restricted=False,
        acl_tags=["repo:spen-sdk"],
        acl_extraction_status="ok",
        extracted_at="2026-07-10T00:00:00Z",
    )

    FoundationSchemaValidator().validate_record("ACLRecord", record)


def test_optional_fields_are_omitted_when_none() -> None:
    record = build_unrestricted_confluence_record()

    assert "crawler_identity" not in record
    assert "restriction_inherited" not in record
    assert "restriction_source_page_ids" not in record
    assert "allowed_users" not in record
    assert "allowed_groups" not in record
    assert "acl_confidence" not in record


def test_empty_optional_lists_and_optional_strings_are_preserved() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880624",
        document_id="confluence:page:938880624",
        source_system="confluence",
        is_restricted=False,
        acl_tags=["space:SVMC"],
        acl_extraction_status="partial",
        extracted_at="2026-07-10T00:00:00Z",
        crawler_identity="",
        restriction_source_page_ids=[],
        allowed_users=[],
        allowed_groups=[],
        acl_confidence="approximate",
    )

    assert record["crawler_identity"] == ""
    assert record["restriction_source_page_ids"] == []
    assert record["allowed_users"] == []
    assert record["allowed_groups"] == []
    FoundationSchemaValidator().validate_record("ACLRecord", record)


def test_partial_optional_fields_are_preserved_and_none_fields_are_omitted() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880626",
        document_id="confluence:page:938880626",
        source_system="confluence",
        is_restricted=True,
        acl_tags=["group:foundation-team"],
        acl_extraction_status="partial",
        extracted_at="2026-07-10T00:00:00Z",
        crawler_identity="svc-foundation-crawler",
        restriction_inherited=None,
        restriction_source_page_ids=["938880600"],
        allowed_users=None,
        allowed_groups=["foundation-team"],
        acl_confidence=None,
    )

    assert record["crawler_identity"] == "svc-foundation-crawler"
    assert record["restriction_source_page_ids"] == ["938880600"]
    assert record["allowed_groups"] == ["foundation-team"]
    assert "restriction_inherited" not in record
    assert "allowed_users" not in record
    assert "acl_confidence" not in record
    FoundationSchemaValidator().validate_record("ACLRecord", record)


def test_list_inputs_are_copied_not_mutated_or_shared() -> None:
    acl_tags = ["user:spen"]
    restriction_source_page_ids = ["938880600"]
    allowed_users = ["spen"]
    allowed_groups = ["foundation-team"]

    record = ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880625",
        document_id="confluence:page:938880625",
        source_system="confluence",
        is_restricted=True,
        acl_tags=acl_tags,
        acl_extraction_status="ok",
        extracted_at="2026-07-10T00:00:00Z",
        restriction_source_page_ids=restriction_source_page_ids,
        allowed_users=allowed_users,
        allowed_groups=allowed_groups,
    )

    acl_tags.append("group:mutated")
    restriction_source_page_ids.append("938880601")
    allowed_users.append("mutated")
    allowed_groups.append("mutated-team")

    assert record["acl_tags"] == ["user:spen"]
    assert record["restriction_source_page_ids"] == ["938880600"]
    assert record["allowed_users"] == ["spen"]
    assert record["allowed_groups"] == ["foundation-team"]

    record["acl_tags"].append("group:record-only")  # type: ignore[attr-defined]
    record["restriction_source_page_ids"].append(  # type: ignore[attr-defined]
        "938880602"
    )
    record["allowed_users"].append("record-only")  # type: ignore[attr-defined]
    record["allowed_groups"].append("record-only-team")  # type: ignore[attr-defined]

    assert acl_tags == ["user:spen", "group:mutated"]
    assert restriction_source_page_ids == ["938880600", "938880601"]
    assert allowed_users == ["spen", "mutated"]
    assert allowed_groups == ["foundation-team", "mutated-team"]


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("acl_id", 123, TypeError),
        ("acl_id", "", ValueError),
        ("document_id", 123, TypeError),
        ("document_id", "", ValueError),
        ("source_system", 123, TypeError),
        ("source_system", "", ValueError),
        ("acl_extraction_status", 123, TypeError),
        ("acl_extraction_status", "", ValueError),
        ("extracted_at", 123, TypeError),
        ("extracted_at", "", ValueError),
    ],
)
def test_invalid_required_string_input_fails(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    kwargs = {
        "acl_id": "acl:confluence:page:938880621",
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "is_restricted": False,
        "acl_tags": ["space:SVMC"],
        "acl_extraction_status": "ok",
        "extracted_at": "2026-07-10T00:00:00Z",
    }
    kwargs[field_name] = value

    with pytest.raises(error_type, match=field_name):
        ACLRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("is_restricted", ["false", 0, 1, None])
def test_non_bool_is_restricted_fails(is_restricted: object) -> None:
    with pytest.raises(TypeError, match="is_restricted expects bool"):
        ACLRecordBuilder.build(
            acl_id="acl:confluence:page:938880621",
            document_id="confluence:page:938880621",
            source_system="confluence",
            is_restricted=is_restricted,  # type: ignore[arg-type]
            acl_tags=["space:SVMC"],
            acl_extraction_status="ok",
            extracted_at="2026-07-10T00:00:00Z",
        )


@pytest.mark.parametrize("restriction_inherited", ["true", 0, 1])
def test_non_bool_restriction_inherited_fails(
    restriction_inherited: object,
) -> None:
    with pytest.raises(TypeError, match="restriction_inherited expects bool"):
        ACLRecordBuilder.build(
            acl_id="acl:confluence:page:938880621",
            document_id="confluence:page:938880621",
            source_system="confluence",
            is_restricted=False,
            acl_tags=["space:SVMC"],
            acl_extraction_status="ok",
            extracted_at="2026-07-10T00:00:00Z",
            restriction_inherited=restriction_inherited,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("acl_tags", ["space:SVMC", []])
def test_invalid_acl_tags_fails(acl_tags: object) -> None:
    expected_error = TypeError if isinstance(acl_tags, str) else ValueError

    with pytest.raises(expected_error, match="acl_tags"):
        ACLRecordBuilder.build(
            acl_id="acl:confluence:page:938880621",
            document_id="confluence:page:938880621",
            source_system="confluence",
            is_restricted=False,
            acl_tags=acl_tags,  # type: ignore[arg-type]
            acl_extraction_status="ok",
            extracted_at="2026-07-10T00:00:00Z",
        )


@pytest.mark.parametrize(
    "field_name",
    ["restriction_source_page_ids", "allowed_users", "allowed_groups"],
)
def test_non_list_optional_list_input_fails(field_name: str) -> None:
    kwargs = {
        "acl_id": "acl:confluence:page:938880621",
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "is_restricted": False,
        "acl_tags": ["space:SVMC"],
        "acl_extraction_status": "ok",
        "extracted_at": "2026-07-10T00:00:00Z",
        field_name: "not-a-list",
    }

    with pytest.raises(TypeError, match=f"{field_name} expects list"):
        ACLRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["crawler_identity", "acl_confidence"])
def test_non_string_optional_string_input_fails(field_name: str) -> None:
    kwargs = {
        "acl_id": "acl:confluence:page:938880621",
        "document_id": "confluence:page:938880621",
        "source_system": "confluence",
        "is_restricted": False,
        "acl_tags": ["space:SVMC"],
        "acl_extraction_status": "ok",
        "extracted_at": "2026-07-10T00:00:00Z",
        field_name: 123,
    }

    with pytest.raises(TypeError, match=f"{field_name} expects str"):
        ACLRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


def test_acl_id_matches_caller_provided_value() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:caller-owned-id",
        document_id="confluence:page:938880621",
        source_system="confluence",
        is_restricted=False,
        acl_tags=["space:SVMC"],
        acl_extraction_status="ok",
        extracted_at="2026-07-10T00:00:00Z",
    )

    assert record["acl_id"] == "acl:caller-owned-id"


def test_schema_validator_owns_enum_and_tag_grammar_validation() -> None:
    record = ACLRecordBuilder.build(
        acl_id="acl:confluence:page:938880621",
        document_id="confluence:page:938880621",
        source_system="unknown",
        is_restricted=False,
        acl_tags=["bad-tag"],
        acl_extraction_status="not-a-status",
        extracted_at="2026-07-10T00:00:00Z",
    )

    with pytest.raises(FoundationValidationError):
        FoundationSchemaValidator().validate_record("ACLRecord", record)
