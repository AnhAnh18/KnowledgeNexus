from __future__ import annotations

import inspect

import pytest

from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointFailureCategory,
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
    CheckpointSchemaState,
    CheckpointStateError,
    InventoryWorkItem,
)
from knowledgenexus.foundation.domain.models import (
    CanonicalIncludeRoots,
    CommittedCheckpointTransition,
    CrawlRunId,
    IncludeRootProgress,
)

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("root",))


def _transition() -> CommittedCheckpointTransition:
    return CommittedCheckpointTransition(
        RUN,
        0,
        "root",
        IncludeRootProgress.DESCENDANTS_PENDING,
        IncludeRootProgress.DESCENDANTS_PENDING,
        2,
        ROOTS,
    )


def test_safe_schema_dto_and_error_surface() -> None:
    assert CheckpointSchemaState(1).schema_version == 1
    error = CheckpointStateError()
    assert str(error) == "checkpoint_failure"
    assert repr(error) == "CheckpointStateError('checkpoint_failure')"
    assert error.args == ("checkpoint_failure",)
    assert error.category is CheckpointFailureCategory.CHECKPOINT_FAILURE
    assert not hasattr(error, "path")
    assert not hasattr(error, "connection")
    assert not any(name in inspect.signature(CheckpointStateError).parameters for name in ("message", "cause"))


@pytest.mark.parametrize("version", [-1, True, "1", None])
def test_invalid_schema_version_is_sanitized(version) -> None:
    with pytest.raises(CheckpointStateError) as caught:
        CheckpointSchemaState(version)
    assert str(caught.value) == "checkpoint_failure"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_inventory_work_item_is_typed_and_redacts_identities_in_repr() -> None:
    root = InventoryWorkItem(RUN, 0, "root", "root", None, 50)
    window = InventoryWorkItem(RUN, 0, "root", "window", 100, 50)
    assert root.next_start is None
    assert window.next_start == 100
    assert "123e4567" not in repr(window)
    assert "root" not in repr(window)
    with pytest.raises(ValueError): InventoryWorkItem(RUN, 0, "root", "root", 0, 50)
    with pytest.raises(ValueError): InventoryWorkItem(RUN, 0, "root", "window", None, 50)
    with pytest.raises(ValueError): InventoryWorkItem(RUN, 0, "root", "window", 0, 0)
    with pytest.raises(ValueError): InventoryWorkItem(RUN, 0, "root", "window", True, 50)
    with pytest.raises(TypeError): InventoryWorkItem(RUN.value, 0, "root", "root", None, 50)


def test_checkpoint_commit_result_is_typed_and_safe_to_render() -> None:
    result = CheckpointCommitResult(_transition(), replayed=False)
    replay = CheckpointCommitResult(_transition(), replayed=True)
    assert result.transition == _transition()
    assert replay.replayed is True
    assert repr(result) == "CheckpointCommitResult(replayed=False)"
    with pytest.raises(TypeError): CheckpointCommitResult(_transition(), 0)


def test_operation_failures_expose_only_stable_categories() -> None:
    failure = CheckpointOperationFailure(
        CheckpointOperationFailureCategory.INVENTORY_PAGE_BUDGET_EXHAUSTED
    )
    assert str(failure) == "inventory_page_budget_exhausted"
    assert repr(failure) == (
        "CheckpointOperationFailure('inventory_page_budget_exhausted')"
    )
    assert failure.category is CheckpointOperationFailureCategory.PAGE_BUDGET_EXHAUSTED
    assert not hasattr(failure, "details")
    with pytest.raises(TypeError): CheckpointOperationFailure("state_conflict")
