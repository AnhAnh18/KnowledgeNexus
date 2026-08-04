import pytest

from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopDecision,
    ControlledStopController,
    ControlledStopPolicy,
    is_inventory_window_commit,
)
from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    DurableInventoryRunResult,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    ConfluenceCrawlFingerprint,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CanonicalIncludeRoots,
    CommittedCheckpointTransition,
    CrawlRunId,
    CrawlRunSnapshot,
    CrawlRunStatus,
    IncludeRootProgress,
    InventoryPhaseStatus,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunSelectionFailure,
)


RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("root",))


def _result(from_progress, to_progress, *, replayed=False, sequence=1):
    return CheckpointCommitResult(
        CommittedCheckpointTransition(
            RUN,
            0,
            "root",
            from_progress,
            to_progress,
            sequence,
            ROOTS,
        ),
        replayed,
    )


def test_controller_counts_only_new_descendant_window_commits() -> None:
    controller = ControlledStopController(ControlledStopPolicy(2))
    assert controller.record(
        _result(IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED)
    ).status == "continue"
    assert controller.record(
        _result(
            IncludeRootProgress.DESCENDANTS_PENDING,
            IncludeRootProgress.DESCENDANTS_PENDING,
            replayed=True,
        )
    ).committed_count == 0
    assert controller.record(
        _result(
            IncludeRootProgress.DESCENDANTS_PENDING,
            IncludeRootProgress.DESCENDANTS_PENDING,
        )
    ).status == "continue"
    decision = controller.record(
        _result(
            IncludeRootProgress.DESCENDANTS_PENDING,
            IncludeRootProgress.DESCENDANTS_COMPLETE,
            sequence=2,
        )
    )
    assert decision.status == "pause"
    assert decision.reason == "controlled_checkpoint_stop"
    assert decision.committed_count == 2


def test_policy_rejects_zero_bool_and_negative_thresholds() -> None:
    for value in (0, False, -1, 1.0):
        with pytest.raises((TypeError, ValueError)):
            ControlledStopPolicy(value)


def test_classifier_requires_typed_transition() -> None:
    with pytest.raises(TypeError):
        is_inventory_window_commit(object())


def test_nonpaused_results_reject_controlled_stop_metadata() -> None:
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "selection_failed",
            selection_failure=CheckpointRunSelectionFailure("run_not_found"),
            reason="controlled_checkpoint_stop",
            controlled_stop_committed_count=1,
            controlled_stop_threshold=1,
        )


def test_paused_results_require_positive_threshold_and_snapshot() -> None:
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "paused",
            reason="controlled_checkpoint_stop",
            controlled_stop_committed_count=1,
            controlled_stop_threshold=None,
        )


def test_pause_decision_requires_reached_threshold() -> None:
    with pytest.raises(ValueError):
        ControlledStopDecision("pause", 0, 1, "controlled_checkpoint_stop")


def test_result_status_matrix_rejects_missing_or_extraneous_state() -> None:
    selection_failure = CheckpointRunSelectionFailure("run_not_found")
    fingerprint = ConfluenceCrawlFingerprint._from_digest("a" * 64)
    snapshot = CrawlRunSnapshot(
        RUN,
        RUN,
        fingerprint,
        CrawlRunStatus.INCOMPLETE,
        InventoryPhaseStatus.PENDING,
        ROOTS,
        (IncludeRootProgress.ROOT_PENDING,),
    )

    with pytest.raises(ValueError):
        DurableInventoryRunResult("completed")
    with pytest.raises(ValueError):
        DurableInventoryRunResult("inventory_complete")
    root_commit = _result(
        IncludeRootProgress.ROOT_PENDING,
        IncludeRootProgress.ROOT_COMMITTED,
    )
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "inventory_complete",
            committed=(root_commit,),
            snapshot=snapshot,
        )
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "selection_failed",
            selection_failure=selection_failure,
            snapshot=snapshot,
        )
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "selection_failed",
            committed=(root_commit,),
            selection_failure=selection_failure,
        )
    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "operation_failed",
            operation_failure=CheckpointOperationFailure(
                CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
            ),
        )


def test_paused_result_count_matches_new_descendant_window_commits() -> None:
    fingerprint = ConfluenceCrawlFingerprint._from_digest("a" * 64)
    snapshot = CrawlRunSnapshot(
        RUN,
        RUN,
        fingerprint,
        CrawlRunStatus.INCOMPLETE,
        InventoryPhaseStatus.PENDING,
        ROOTS,
        (IncludeRootProgress.ROOT_PENDING,),
    )
    window = _result(
        IncludeRootProgress.DESCENDANTS_PENDING,
        IncludeRootProgress.DESCENDANTS_PENDING,
    )

    with pytest.raises(ValueError):
        DurableInventoryRunResult(
            "paused",
            committed=(window,),
            reason="controlled_checkpoint_stop",
            controlled_stop_committed_count=2,
            controlled_stop_threshold=1,
            snapshot=snapshot,
        )
