from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    DurableInventoryRunResult,
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopPolicy,
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
    InventoryRootCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryWindowCommit,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunInventoryComplete,
    CheckpointRunSelectionFailure,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
    CheckpointStateError,
    InventoryWorkItem,
)


PROFILE = {
    "profile_id": "m7-crawl-reliability-v1",
    "profile_version": "1",
    "inventory_page_size": 50,
    "attachment_page_size": 50,
    "minimum_request_interval_seconds": 3.0,
    "max_response_bytes_per_request": 8388608,
    "max_total_requests_per_run": 50000,
    "max_attempts": 4,
    "base_backoff_seconds": 1.0,
    "max_retry_delay_seconds": 120.0,
    "max_total_retry_delay_seconds": 300.0,
    "jitter": False,
    "max_include_roots": 16,
    "max_pages_per_run": 10000,
    "max_inventory_windows_per_root": 1000,
    "max_inventory_windows_per_run": 4000,
    "max_restriction_targets_per_page": 256,
    "max_restriction_observations_per_run": 25000,
    "max_attachment_windows_per_page": 100,
    "max_attachment_windows_per_run": 10000,
    "max_raw_bytes_per_run": 34359738368,
    "max_raw_artifacts_per_run": 250000,
    "minimum_free_disk_reserve_bytes": 8589934592,
}

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("root",))
FINGERPRINT = ConfluenceCrawlFingerprint._from_digest("a" * 64)
SNAPSHOT = CrawlRunSnapshot(
    RUN,
    RUN,
    FINGERPRINT,
    CrawlRunStatus.INCOMPLETE,
    InventoryPhaseStatus.PENDING,
    ROOTS,
    (IncludeRootProgress.ROOT_PENDING,),
)


def _request(tmp_path: Path, request_type=StartNewRunRequest):
    config = ConfluenceSourceConfig(
        "source", "SPACE", (ConfluenceIncludeRoot("root"),)
    )
    if request_type is ResumeExplicitRunRequest:
        return request_type(tmp_path, RUN, "https://example.invalid/confluence", config, PROFILE)
    return request_type(tmp_path, "https://example.invalid/confluence", config, PROFILE)


class FakeActivation:
    snapshot = SNAPSHOT
    session_id = object()

    def __init__(self, works):
        self.works = list(works)
        self.commits = []
        self.reserver_seen = False

    def check_outbound_attempt(self):
        self.reserver_seen = True
        return None

    def reserve_outbound_attempt(self):
        self.reserver_seen = True
        return object()

    def load_next_inventory_work(self):
        return self.works.pop(0)

    def read_schema_state(self):
        raise AssertionError("not part of orchestration")

    def stream_inventory_occurrences(self, *, batch_size=256):
        raise AssertionError("not part of orchestration")

    def commit_root_occurrence(self, command):
        self.commits.append(command)
        return CheckpointCommitResult(
            CommittedCheckpointTransition(
                RUN,
                0,
                "root",
                IncludeRootProgress.ROOT_PENDING,
                IncludeRootProgress.ROOT_COMMITTED,
                len(self.commits) - 1,
                ROOTS,
            ),
            False,
        )

    def commit_inventory_window(self, command):
        self.commits.append(command)
        from_progress = (
            IncludeRootProgress.DESCENDANTS_PENDING
            if len(self.commits) == 2
            else IncludeRootProgress.DESCENDANTS_PENDING
        )
        to_progress = (
            IncludeRootProgress.DESCENDANTS_PENDING
            if not command.window.is_terminal
            else IncludeRootProgress.DESCENDANTS_COMPLETE
        )
        return CheckpointCommitResult(
            CommittedCheckpointTransition(
                RUN,
                0,
                "root",
                from_progress,
                to_progress,
                len(self.commits) - 1,
                ROOTS,
            ),
            False,
        )


class FakeWindowPort:
    def __init__(self, activation, *, malformed=False):
        self.activation = activation
        self.malformed = malformed
        self.calls = []

    def fetch_root_metadata(self, *, space_key, root_page_id):
        self.calls.append(("root", root_page_id))
        return ConfluencePageMetadata("root", "Root", space_key)

    def fetch_descendants_window(self, *, space_key, root_page_id, start, page_size):
        self.calls.append(("window", start, page_size))
        child = ConfluencePageMetadata(
            f"child-{start}",
            f"Child {start}",
            space_key,
            root_page_id,
            (root_page_id,),
            ("Root",),
        )
        if self.malformed:
            start += 1
        return ConfluenceInventoryWindow((child,), start, page_size, 1, start + 1)


class FakeRunPort:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.exits = []

    @contextmanager
    def _yield(self, name, request):
        self.calls.append(name)
        try:
            yield self.outcome
        finally:
            self.exits.append(name)

    def start_new_run(self, request):
        return self._yield("start", request)

    def resume_explicit_run_id(self, request):
        return self._yield("explicit", request)

    def resume_unique_incomplete_run(self, request):
        return self._yield("unique", request)


def _works():
    return [
        InventoryWorkItem(RUN, 0, "root", "root", None, 50),
        InventoryWorkItem(RUN, 0, "root", "window", 0, 50),
        InventoryWorkItem(RUN, 0, "root", "window", 1, 50),
        None,
    ]


def test_orchestrator_commits_one_root_then_each_window(tmp_path) -> None:
    activation = FakeActivation(_works())
    window_port = FakeWindowPort(activation)
    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: window_port,
    )

    result = use_case.execute(request=_request(tmp_path))

    assert isinstance(result, DurableInventoryRunResult)
    assert result.status == "completed"
    assert len(result.committed) == 3
    assert [call[0] for call in window_port.calls] == ["root", "window", "window"]
    assert [type(command) for command in activation.commits] == [
        InventoryRootCommit,
        InventoryWindowCommit,
        InventoryWindowCommit,
    ]


def test_orchestrator_passes_activation_to_window_factory(tmp_path) -> None:
    activation = FakeActivation(_works())
    transport_seen = []
    window_seen = []
    port = FakeWindowPort(activation)
    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: (
            transport_seen.append(value) or "retry-transport"
        ),
        inventory_window_port_factory=lambda value: (
            window_seen.append(value) or port
        ),
    )
    use_case.execute(request=_request(tmp_path))
    assert transport_seen == [activation]
    assert window_seen == ["retry-transport"]


def test_orchestrator_pauses_after_requested_new_window_commit(tmp_path) -> None:
    activation = FakeActivation(_works())
    window_port = FakeWindowPort(activation)
    run_port = FakeRunPort(activation)
    result = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=run_port,
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: window_port,
    ).execute(
        request=_request(tmp_path),
        controlled_stop_policy=ControlledStopPolicy(1),
    )

    assert result.status == "paused"
    assert result.reason == "controlled_checkpoint_stop"
    assert result.controlled_stop_committed_count == 1
    assert result.controlled_stop_threshold == 1
    assert len(result.committed) == 2
    assert [call[0] for call in window_port.calls] == ["root", "window"]
    assert len(activation.works) == 2
    assert run_port.exits == ["start"]


def test_disabled_controlled_stop_preserves_completion(tmp_path) -> None:
    activation = FakeActivation(_works())
    result = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: FakeWindowPort(activation),
    ).execute(request=_request(tmp_path), controlled_stop_policy=ControlledStopPolicy())
    assert result.status == "completed"
    assert result.reason is None


def test_orchestrator_branches_selection_and_inventory_complete(tmp_path) -> None:
    failure = CheckpointRunSelectionFailure("run_not_found")
    failed = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(failure),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: FakeWindowPort(None),
    ).execute(request=_request(tmp_path, ResumeUniqueIncompleteRunRequest))
    assert failed.status == "selection_failed"

    complete = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(CheckpointRunInventoryComplete(SNAPSHOT)),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: FakeWindowPort(None),
    ).execute(request=_request(tmp_path, ResumeExplicitRunRequest))
    assert complete.status == "inventory_complete"


def test_orchestrator_returns_typed_operation_failure_without_fetch(tmp_path) -> None:
    failure = CheckpointOperationFailure(
        CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
    )
    activation = FakeActivation([failure])
    window_port = FakeWindowPort(activation)
    result = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: window_port,
    ).execute(request=_request(tmp_path))
    assert result.status == "operation_failed"
    assert result.operation_failure is failure
    assert window_port.calls == []


def test_orchestrator_rejects_malformed_window_result(tmp_path) -> None:
    activation = FakeActivation(
        [InventoryWorkItem(RUN, 0, "root", "window", 0, 50)]
    )
    with pytest.raises(CheckpointStateError):
        ExecuteDurableConfluenceInventory(
            checkpoint_run_port=FakeRunPort(activation),
            inventory_transport_factory=lambda value: value,
            inventory_window_port_factory=lambda value: FakeWindowPort(
                activation, malformed=True
            ),
        ).execute(request=_request(tmp_path))


def test_invalid_request_fails_closed_before_factories_are_called(tmp_path) -> None:
    run_port = FakeRunPort(None)
    transport_calls = []
    window_calls = []
    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=run_port,
        inventory_transport_factory=lambda value: transport_calls.append(value),
        inventory_window_port_factory=lambda value: window_calls.append(value),
    )

    with pytest.raises(CheckpointStateError):
        use_case.execute(request=object())

    assert run_port.calls == []
    assert transport_calls == []
    assert window_calls == []


def test_operation_failure_preserves_prior_durable_commits(tmp_path) -> None:
    failure = CheckpointOperationFailure(
        CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
    )
    activation = FakeActivation([_works()[0], failure])
    result = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: FakeWindowPort(activation),
    ).execute(request=_request(tmp_path))

    assert result.status == "operation_failed"
    assert result.operation_failure is failure
    assert len(result.committed) == 1


def test_commit_failure_preserves_prior_durable_commits(tmp_path) -> None:
    failure = CheckpointOperationFailure(
        CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
    )
    activation = FakeActivation(_works()[:2])
    activation.commit_inventory_window = lambda command: failure
    result = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=FakeRunPort(activation),
        inventory_transport_factory=lambda value: value,
        inventory_window_port_factory=lambda value: FakeWindowPort(activation),
    ).execute(request=_request(tmp_path))

    assert result.status == "operation_failed"
    assert result.operation_failure is failure
    assert len(result.committed) == 1
