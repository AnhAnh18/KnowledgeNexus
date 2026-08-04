from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import uuid

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CrawlSessionId,
    InventoryRootCommit,
    ResumeExplicitRunId,
    StartNewRun,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
    InventoryWindowCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.checkpoint import (
    sqlite_checkpoint_workspace as workspace_module,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _RunActivated,
    _RunRegistryRequest,
    _register_checkpoint_run,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
    CheckpointReservationResult,
    CheckpointStateError,
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


def _request(path, *, profile=None, roots=("root",)) -> _RunRegistryRequest:
    return _RunRegistryRequest(
        path,
        StartNewRun(),
        "https://example.invalid/confluence",
        ConfluenceSourceConfig(
            "source",
            "SPACE",
            tuple(ConfluenceIncludeRoot(root) for root in roots),
        ),
        dict(profile or PROFILE),
    )


def _clock() -> datetime:
    return datetime(2026, 8, 1, 1, 2, 3, 456789, tzinfo=timezone.utc)


def _ids(*values: str):
    iterator = iter(values)
    return lambda: uuid.UUID(next(iterator))


def _start(path, *, profile=None, roots=("root",)):
    return _register_checkpoint_run(
        _request(path, profile=profile, roots=roots),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )


def test_reserve_outbound_attempt_is_durable_and_denies_at_cap(tmp_path) -> None:
    with _start(tmp_path) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_total_requests_per_run=2
        )
        first = activation.reserve_outbound_attempt()
        second = activation.reserve_outbound_attempt()
        denied = activation.reserve_outbound_attempt()
        assert isinstance(first, CheckpointReservationResult)
        assert isinstance(second, CheckpointReservationResult)
        assert (first.reservation_sequence, second.reservation_sequence) == (0, 1)
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED
        run_id = activation.snapshot.run_id

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        rows = workspace._mutate(
            lambda transaction: transaction._fetchall(
                "SELECT reservation_sequence,reserved_at FROM request_budget_reservations "
                "WHERE run_id=? ORDER BY reservation_sequence",
                (run_id.value,),
            )
        )
    assert rows == [
        (0, "2026-08-01T01:02:03.456Z"),
        (1, "2026-08-01T01:02:03.456Z"),
    ]

    resume_request = replace(
        _request(tmp_path),
        operation=ResumeExplicitRunId(run_id),
    )
    with _register_checkpoint_run(resume_request, utc_now=_clock) as resumed:
        resumed._state._limits = replace(
            resumed._state._limits, max_total_requests_per_run=2
        )
        assert resumed.snapshot.run_id == run_id
        denied_again = resumed.reserve_outbound_attempt()
        assert isinstance(denied_again, CheckpointOperationFailure)
        assert denied_again.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED


def test_reservation_rejects_a_session_that_is_no_longer_active(tmp_path) -> None:
    with _start(tmp_path) as activation:
        activation._state._session_id = CrawlSessionId("not-the-active-session")
        with pytest.raises(CheckpointStateError):
            activation.reserve_outbound_attempt()


def _root_commit(activation: _RunActivated, root_id: str = "root") -> InventoryRootCommit:
    metadata = ConfluencePageMetadata(root_id, root_id.title(), "SPACE")
    return InventoryRootCommit(
        activation.snapshot.run_id,
        activation.snapshot.include_roots.ordinal_for(root_id),
        root_id,
        metadata,
        activation.snapshot.include_roots,
    )


def _window_commit(
    activation: _RunActivated,
    start: int,
    page_ids: tuple[str, ...],
    total_size: int,
    root_id: str | None = None,
) -> InventoryWindowCommit:
    root_id = root_id or activation.snapshot.include_roots.root_ids[0]
    ordinal = activation.snapshot.include_roots.ordinal_for(root_id)
    items = tuple(
        ConfluencePageMetadata(
            page_id,
            page_id.title(),
            "SPACE",
            root_id,
            (root_id,),
            (root_id.title(),),
        )
        for page_id in page_ids
    )
    window = ConfluenceInventoryWindow(
        items, start, 50, len(items), total_size
    )
    occurrences = tuple(
        InventoryOccurrence(
            activation.snapshot.run_id,
            ordinal,
            root_id,
            start,
            index,
            page_id,
            items[index],
            activation.snapshot.include_roots,
        )
        for index, page_id in enumerate(page_ids)
    )
    return InventoryWindowCommit(
        activation.snapshot.run_id,
        ordinal,
        root_id,
        start,
        window,
        occurrences,
        activation.snapshot.include_roots,
    )


def test_root_and_terminal_window_replay_is_idempotent_and_ordered(tmp_path) -> None:
    with _start(tmp_path) as activation:
        root = activation.load_next_inventory_work()
        assert root is not None and root.kind == "root"
        root_command = _root_commit(activation)
        assert activation.commit_root_occurrence(root_command).replayed is False
        assert activation.commit_root_occurrence(root_command).replayed is True

        window_work = activation.load_next_inventory_work()
        assert window_work is not None and window_work.next_start == 0
        command = _window_commit(activation, 0, ("child",), 1)
        assert activation.commit_inventory_window(command).replayed is False
        assert activation.commit_inventory_window(command).replayed is True
        assert activation.load_next_inventory_work() is None
        facts = tuple(activation.stream_inventory_occurrences())
        assert [
            getattr(fact, "page_id", getattr(fact, "metadata", None).page_id)
            for fact in facts
        ] == [
            "root",
            "child",
        ]


def test_inventory_readback_is_bounded_and_root_before_window_ordered(tmp_path) -> None:
    with _start(tmp_path, roots=("b", "a")) as activation:
        for root_id in activation.snapshot.include_roots.root_ids:
            activation.load_next_inventory_work()
            activation.commit_root_occurrence(_root_commit(activation, root_id))
            activation.load_next_inventory_work()
            activation.commit_inventory_window(
                _window_commit(activation, 0, (f"{root_id}-1",), 2, root_id)
            )
            activation.load_next_inventory_work()
            activation.commit_inventory_window(
                _window_commit(activation, 1, (f"{root_id}-2",), 2, root_id)
            )

        facts = tuple(activation.stream_inventory_occurrences(batch_size=1))

    assert [fact.metadata.page_id for fact in facts] == [
        "a",
        "a-1",
        "a-2",
        "b",
        "b-1",
        "b-2",
    ]


def test_inventory_readback_rejects_invalid_batch_and_stale_iterator(tmp_path) -> None:
    with _start(tmp_path) as activation:
        with pytest.raises(CheckpointStateError):
            activation.stream_inventory_occurrences(batch_size=0)
        stream = activation.stream_inventory_occurrences(batch_size=1)

    with pytest.raises(CheckpointStateError):
        next(stream)


def test_nonterminal_cursor_and_multi_root_progress_are_durable(tmp_path) -> None:
    with _start(tmp_path, roots=("b", "a")) as activation:
        for root_index, root_id in enumerate(activation.snapshot.include_roots.root_ids):
            work = activation.load_next_inventory_work()
            assert work is not None and work.include_root_page_id == root_id
            activation.commit_root_occurrence(_root_commit(activation, root_id))
            window = activation.load_next_inventory_work()
            assert window is not None and window.next_start == 0
            first = _window_commit(activation, 0, (f"{root_id}-1",), 2, root_id)
            activation.commit_inventory_window(first)
            next_work = activation.load_next_inventory_work()
            assert next_work is not None and next_work.next_start == 1
            second = _window_commit(activation, 1, (f"{root_id}-2",), 2, root_id)
            activation.commit_inventory_window(second)
        assert activation.load_next_inventory_work() is None


def test_page_budget_failure_rolls_back_window_rows_and_cursor(tmp_path) -> None:
    with _start(tmp_path) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_pages_per_run=1
        )
        activation.load_next_inventory_work()
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        result = activation.commit_inventory_window(
            _window_commit(activation, 0, ("child",), 1)
        )
        assert isinstance(result, CheckpointOperationFailure)
        assert result.category is CheckpointOperationFailureCategory.INVENTORY_PAGE_BUDGET_EXHAUSTED
        work = activation.load_next_inventory_work()
        assert work is not None and work.next_start == 0
        assert tuple(activation.stream_inventory_occurrences())[-1].metadata.page_id == "root"


def test_window_row_fault_rolls_back_all_window_state(tmp_path, monkeypatch) -> None:
    with _start(tmp_path) as activation:
        activation.load_next_inventory_work()
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        command = _window_commit(activation, 0, ("child",), 1)
        transaction_type = workspace_module._PrivateCheckpointTransaction
        original_execute = transaction_type._execute

        def fail_on_occurrence_insert(transaction, sql, parameters=()):
            if "INSERT INTO inventory_occurrences" in sql:
                raise RuntimeError("injected occurrence fault")
            return original_execute(transaction, sql, parameters)

        monkeypatch.setattr(transaction_type, "_execute", fail_on_occurrence_insert)
        with pytest.raises(CheckpointStateError):
            activation.commit_inventory_window(command)

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        rows = workspace._mutate(
            lambda transaction: (
                transaction._fetchall("SELECT * FROM inventory_windows"),
                transaction._fetchall("SELECT * FROM inventory_occurrences"),
                transaction._fetchall("SELECT progress,next_start FROM root_progress"),
                transaction._fetchall("SELECT * FROM checkpoint_transitions"),
            )
        )
    assert rows[0] == []
    assert rows[1] == []
    assert rows[2][0][0:2] == ("descendants_pending", 0)
    assert len(rows[3]) == 2


def test_stale_activation_is_rejected_after_context_exit(tmp_path) -> None:
    with _start(tmp_path) as activation:
        retained = activation
    with pytest.raises(CheckpointStateError):
        retained.load_next_inventory_work()


def test_malformed_terminal_cursor_is_rejected_on_resume(tmp_path) -> None:
    with _start(tmp_path) as activation:
        run_id = activation.snapshot.run_id.value
    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(
                "UPDATE root_progress SET progress='descendants_complete',"
                "next_start=1,descendants_complete=1 WHERE run_id=?",
                (run_id,),
            )
        )
    with pytest.raises(CheckpointStateError):
        with _register_checkpoint_run(
            _request(tmp_path),
            uuid4=_ids("223e4567-e89b-42d3-a456-426614174000"),
            utc_now=_clock,
        ):
            pass


@pytest.mark.parametrize(
    "tamper_sql",
    (
        "UPDATE request_budget_reservations SET reserved_at='not-a-timestamp'",
        "UPDATE request_budget_reservations SET reservation_sequence=3",
    ),
)
def test_resume_rejects_malformed_request_reservation_rows(tmp_path, tamper_sql) -> None:
    with _start(tmp_path) as activation:
        reservation = activation.reserve_outbound_attempt()
        assert isinstance(reservation, CheckpointReservationResult)
        run_id = activation.snapshot.run_id

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(tamper_sql)
        )

    request = replace(
        _request(tmp_path), operation=ResumeExplicitRunId(run_id)
    )
    with pytest.raises(CheckpointStateError):
        with _register_checkpoint_run(
            request,
            uuid4=_ids("223e4567-e89b-42d3-a456-426614174002"),
            utc_now=_clock,
        ):
            pass


@pytest.mark.parametrize(
    "tamper_sql",
    (
        "UPDATE inventory_occurrences SET ancestor_page_ids_json='not-json'",
        "UPDATE inventory_occurrences SET item_ordinal=3",
        "DELETE FROM inventory_occurrences",
        "DELETE FROM root_occurrences",
        "UPDATE checkpoint_transitions SET to_progress='descendants_pending'",
        "UPDATE crawl_runs SET inventory_phase='pending'",
    ),
)
def test_resume_rejects_tampered_durable_inventory_facts(tmp_path, tamper_sql) -> None:
    with _start(tmp_path) as activation:
        activation.load_next_inventory_work()
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        activation.commit_inventory_window(_window_commit(activation, 0, ("child",), 1))
        run_id = activation.snapshot.run_id

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(tamper_sql)
        )

    request = replace(
        _request(tmp_path), operation=ResumeExplicitRunId(run_id)
    )
    with pytest.raises(CheckpointStateError):
        with _register_checkpoint_run(
            request,
            uuid4=_ids("223e4567-e89b-42d3-a456-426614174001"),
            utc_now=_clock,
        ):
            pass
