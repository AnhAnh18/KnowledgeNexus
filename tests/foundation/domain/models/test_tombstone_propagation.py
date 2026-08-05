import pytest
import knowledgenexus.foundation.domain.models.tombstone_propagation as tombstone_module

from knowledgenexus.foundation.domain.models import (
    TombstoneEntityType,
    TombstoneProjectionFailureCategory,
    TombstoneProjectionMetrics,
    TombstoneProjectionRequest,
    TombstoneProjectionResult,
    TombstoneProjectionStatus,
    TombstoneReason,
    TombstoneTarget,
)
from knowledgenexus.foundation.domain.rules import TombstoneIdGenerator


def test_request_normalizes_timestamp_and_validates_target() -> None:
    request = TombstoneProjectionRequest(
        root=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1", detail="café"),
        reason=TombstoneReason.SOURCE_DELETED,
        detected_at="2026-08-05T10:00:00+07:00",
        dataset_version="v1",
    )
    assert request.detected_at == "2026-08-05T03:00:00.000000Z"


@pytest.mark.parametrize("value", [None, object(), "chunk:bad"])
def test_invalid_chunk_target_fails_closed(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        TombstoneTarget(TombstoneEntityType.CHUNK, value)  # type: ignore[arg-type]


def test_non_document_root_cannot_cascade() -> None:
    with pytest.raises(ValueError):
        TombstoneProjectionRequest(
            root=TombstoneTarget(TombstoneEntityType.CHUNK, "chunk:git:" + "a" * 16),
            reason=TombstoneReason.CONTENT_UPDATED,
            detected_at="2026-08-05T00:00:00Z",
            dataset_version="v1",
            children=(TombstoneTarget(TombstoneEntityType.SYMBOL, "sym:1"),),
        )


def test_failed_result_rejects_impossible_payload() -> None:
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.FAILED,
            records=({"x": 1},),
            count=1,
            error_category=None,
        )


def test_metrics_reject_cross_field_count() -> None:
    with pytest.raises(ValueError):
        TombstoneProjectionMetrics(record_count=2, root_count=1, child_count=0)

    with pytest.raises(ValueError):
        TombstoneProjectionMetrics(record_count=1, root_count=0, child_count=1)


def test_result_rejects_non_json_safe_nested_values() -> None:
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(({"value": object()},)),  # type: ignore[arg-type]
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def test_result_rejects_non_tombstone_shape() -> None:
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(({"foo": "bar"},)),  # type: ignore[arg-type]
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def test_result_rejects_forged_tombstone_id() -> None:
    record = {
        "schema_version": "1.0",
        "tombstone_id": "tomb:0000000000000000",
        "entity_type": "document",
        "entity_id": "confluence:page:1",
        "reason": "source_deleted",
        "detected_at": "2026-08-05T00:00:00.000000Z",
        "dataset_version": "v1",
    }
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(record,),
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def test_result_revalidates_forged_metrics() -> None:
    forged = object.__new__(TombstoneProjectionMetrics)
    object.__setattr__(forged, "record_count", 1)
    object.__setattr__(forged, "root_count", 1)
    object.__setattr__(forged, "child_count", 999)
    record = {
        "schema_version": "1.0",
        "tombstone_id": "tomb:0000000000000000",
        "entity_type": "document",
        "entity_id": "confluence:page:1",
        "reason": "source_deleted",
        "detected_at": "2026-08-05T00:00:00.000000Z",
        "dataset_version": "v1",
    }
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(record,),
            count=1,
            metrics=forged,
        )


def test_result_accepts_explicit_null_optional_fields() -> None:
    record = {
        "schema_version": "1.0",
        "tombstone_id": "tomb:0000000000000000",
        "entity_type": "document",
        "entity_id": "confluence:page:1",
        "reason": "source_deleted",
        "detected_at": "2026-08-05T00:00:00.000000Z",
        "dataset_version": "v1",
        "detail": None,
        "source_version_last_seen": None,
    }
    record["tombstone_id"] = TombstoneIdGenerator.generate_tombstone_id(
        entity_type="document",
        entity_id="confluence:page:1",
        reason="source_deleted",
        dataset_version="v1",
    )
    result = TombstoneProjectionResult(
        status=TombstoneProjectionStatus.SUCCESS,
        records=(record,),
        count=1,
        metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
    )
    assert result.records[0]["detail"] is None


def test_forged_request_fails_with_typed_error() -> None:
    forged = object.__new__(TombstoneProjectionRequest)
    with pytest.raises((TypeError, ValueError)):
        TombstoneProjectionRequest.__post_init__(forged)


@pytest.mark.parametrize(
    "model",
    [
        TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
        TombstoneProjectionRequest(
            root=TombstoneTarget(TombstoneEntityType.DOCUMENT, "confluence:page:1"),
            reason=TombstoneReason.SOURCE_DELETED,
            detected_at="2026-08-05T00:00:00Z",
            dataset_version="v1",
        ),
        TombstoneProjectionMetrics(record_count=0, root_count=0, child_count=0),
    ],
)
def test_model_rejects_forged_extra_attributes(model: object) -> None:
    object.__setattr__(model, "extra", 1)
    with pytest.raises((TypeError, ValueError)):
        type(model).__post_init__(model)  # type: ignore[attr-defined]


def test_result_rejects_custom_deepcopy_before_invocation() -> None:
    class _Evil:
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            raise AssertionError("deepcopy must not run")

    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(({"value": _Evil()},)),  # type: ignore[arg-type]
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def test_result_rejects_forged_extra_attributes() -> None:
    result = TombstoneProjectionResult(
        status=TombstoneProjectionStatus.FAILED,
        error_category=TombstoneProjectionFailureCategory.INVALID_REQUEST,
    )
    object.__setattr__(result, "extra", 1)
    with pytest.raises((TypeError, ValueError)):
        TombstoneProjectionResult.__post_init__(result)


@pytest.mark.parametrize("make_cycle", [lambda: _self_list(), lambda: _self_dict()])
def test_result_rejects_cyclic_containers(make_cycle) -> None:
    with pytest.raises((TypeError, ValueError)):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(make_cycle(),),  # type: ignore[arg-type]
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def test_result_contains_unexpected_copy_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    record = {
        "schema_version": "1.0",
        "tombstone_id": TombstoneIdGenerator.generate_tombstone_id(
            entity_type="document", entity_id="confluence:page:1", reason="source_deleted", dataset_version="v1"
        ),
        "entity_type": "document",
        "entity_id": "confluence:page:1",
        "reason": "source_deleted",
        "detected_at": "2026-08-05T00:00:00.000000Z",
        "dataset_version": "v1",
    }
    monkeypatch.setattr(tombstone_module.copy, "deepcopy", lambda value: (_ for _ in ()).throw(RuntimeError("private")))
    with pytest.raises(ValueError):
        TombstoneProjectionResult(
            status=TombstoneProjectionStatus.SUCCESS,
            records=(record,),
            count=1,
            metrics=TombstoneProjectionMetrics(record_count=1, root_count=1, child_count=0),
        )


def _self_list() -> list[object]:
    value: list[object] = []
    value.append(value)
    return value


def _self_dict() -> dict[str, object]:
    value: dict[str, object] = {}
    value["self"] = value
    return value
