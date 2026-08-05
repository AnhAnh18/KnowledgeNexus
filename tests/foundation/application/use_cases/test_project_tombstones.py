from knowledgenexus.foundation.application.use_cases import ProjectTombstones
from knowledgenexus.foundation.domain.models import TombstoneProjectionFailureCategory
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.domain.models import (
    TombstoneEntityType,
    TombstoneProjectionRequest,
    TombstoneProjectionStatus,
    TombstoneReason,
    TombstoneTarget,
)


def _request() -> TombstoneProjectionRequest:
    return TombstoneProjectionRequest(
        root=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
        reason=TombstoneReason.ACCESS_REVOKED,
        detected_at="2026-08-05T00:00:00Z",
        dataset_version="v1",
        children=(
            TombstoneTarget(TombstoneEntityType.SYMBOL, "sym:1"),
            TombstoneTarget(TombstoneEntityType.CHUNK, "chunk:git:" + "a" * 16),
            TombstoneTarget(TombstoneEntityType.ACL, "acl:repo:x"),
            TombstoneTarget(TombstoneEntityType.MEDIA, "media:1"),
            TombstoneTarget(TombstoneEntityType.RELATION, "rel:" + "b" * 16),
        ),
    )


def _project() -> ProjectTombstones:
    return ProjectTombstones(schema_validator=FoundationSchemaValidator())


def test_projects_document_cascade_in_deterministic_order() -> None:
    result = _project().execute(_request())
    assert result.status is TombstoneProjectionStatus.SUCCESS
    assert result.count == 6
    assert [record["entity_type"] for record in result.records] == [
        "document", "chunk", "media", "relation", "acl", "symbol"
    ]
    assert {record["reason"] for record in result.records} == {"access_revoked"}
    assert {record["detected_at"] for record in result.records} == {"2026-08-05T00:00:00.000000Z"}


def test_invalid_runtime_request_fails_before_side_effects() -> None:
    result = _project().execute(object())
    assert result.status is TombstoneProjectionStatus.FAILED
    assert result.count == 0
    assert result.records == ()


def test_forged_request_returns_invalid_request() -> None:
    forged = object.__new__(TombstoneProjectionRequest)
    result = _project().execute(forged)
    assert result.status is TombstoneProjectionStatus.FAILED
    assert result.error_category is TombstoneProjectionFailureCategory.INVALID_REQUEST


def test_child_order_does_not_change_result_bytes() -> None:
    request = _request()
    reversed_request = TombstoneProjectionRequest(
        root=request.root,
        reason=request.reason,
        detected_at=request.detected_at,
        dataset_version=request.dataset_version,
        children=tuple(reversed(request.children)),
    )
    assert _project().execute(request).to_bytes() == _project().execute(reversed_request).to_bytes()


def test_schema_validator_failure_is_sanitized_and_atomic() -> None:
    class _RejectingValidator:
        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            raise ValueError("private validator detail")

    result = ProjectTombstones(schema_validator=_RejectingValidator()).execute(_request())
    assert result.status is TombstoneProjectionStatus.FAILED
    assert result.error_category is TombstoneProjectionFailureCategory.SCHEMA_VALIDATION_FAILED
    assert result.records == ()
    assert result.count == 0
