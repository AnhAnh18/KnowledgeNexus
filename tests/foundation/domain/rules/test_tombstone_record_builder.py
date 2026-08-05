import pytest

from knowledgenexus.foundation.domain.models import TombstoneEntityType, TombstoneReason, TombstoneTarget
from knowledgenexus.foundation.domain.rules import TombstoneRecordBuilder
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


def test_builds_schema_valid_record_with_optional_fields() -> None:
    record = TombstoneRecordBuilder.build(
        target=TombstoneTarget(
            TombstoneEntityType.CHUNK,
            "chunk:git:" + "a" * 16,
            detail="updated",
            source_version_last_seen="a" * 40,
        ),
        reason=TombstoneReason.CONTENT_UPDATED,
        detected_at="2026-08-05T00:00:00.000000Z",
        dataset_version="v1",
        schema_validator=FoundationSchemaValidator(),
    )
    assert record["schema_version"] == "1.0"
    assert record["entity_type"] == "chunk"
    assert record["detail"] == "updated"


def test_schema_validator_failure_is_not_silently_ignored() -> None:
    class _Validator:
        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            raise ValueError("reject")

    with pytest.raises(ValueError):
        TombstoneRecordBuilder.build(
            target=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
            reason=TombstoneReason.SOURCE_DELETED,
            detected_at="2026-08-05T00:00:00.000000Z",
            dataset_version="v1",
            schema_validator=_Validator(),
        )


def test_mutating_validator_is_rejected() -> None:
    class _MutatingValidator:
        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            record.pop("entity_id")

    with pytest.raises(ValueError):
        TombstoneRecordBuilder.build(
            target=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
            reason=TombstoneReason.SOURCE_DELETED,
            detected_at="2026-08-05T00:00:00.000000Z",
            dataset_version="v1",
            schema_validator=_MutatingValidator(),
        )


def test_equal_string_subclass_mutation_is_rejected() -> None:
    class _EqualString(str):
        pass

    class _MutatingValidator:
        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            record["entity_id"] = _EqualString(record["entity_id"])  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        TombstoneRecordBuilder.build(
            target=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
            reason=TombstoneReason.SOURCE_DELETED,
            detected_at="2026-08-05T00:00:00.000000Z",
            dataset_version="v1",
            schema_validator=_MutatingValidator(),
        )


def test_forged_target_fails_with_typed_error() -> None:
    forged = object.__new__(TombstoneTarget)
    with pytest.raises((TypeError, ValueError)):
        TombstoneRecordBuilder.build(
            target=forged,
            reason=TombstoneReason.SOURCE_DELETED,
            detected_at="2026-08-05T00:00:00.000000Z",
            dataset_version="v1",
            schema_validator=FoundationSchemaValidator(),
        )
