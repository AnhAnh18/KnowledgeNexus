from __future__ import annotations

import sqlite3
import uuid
from dataclasses import replace

from test_m7_c5a_offline_harness import _request

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    InventoryRootCommit,
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
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _RunRegistryRequest,
    _register_checkpoint_run,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunSelectionFailure,
    ResumeUniqueIncompleteRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import StartNewRun


def _registry_request(request):
    return _RunRegistryRequest(
        request.workspace,
        StartNewRun(),
        request.endpoint_url,
        request.source_config,
        request.reliability_profile,
    )


def _snapshot(workspace):
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3").fetchall()
            for table in (
                "crawl_runs",
                "crawl_sessions",
                "root_progress",
                "inventory_windows",
                "inventory_occurrences",
                "checkpoint_transitions",
                "request_budget_reservations",
            )
        }


def _assert_same_except_reservations(before, after, reservation_delta=0):
    for table in before:
        if table != "request_budget_reservations":
            assert after[table] == before[table], table
    assert len(after["request_budget_reservations"]) == (
        len(before["request_budget_reservations"]) + reservation_delta
    )


class _RequestProbe:
    def __init__(self, activation):
        self.activation = activation
        self.calls = 0

    def request(self):
        result = self.activation.reserve_outbound_attempt()
        if isinstance(result, CheckpointOperationFailure):
            return result
        self.calls += 1
        return result


def test_unique_resume_ambiguous_is_typed_and_nonmutating(tmp_path):
    workspace = tmp_path / "ambiguous"
    workspace.mkdir()
    request = _request(workspace)
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation.pause_session()

    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        run_id, generation_id, digest, status, phase, created_at = db.execute(
            "SELECT run_id,generation_id,fingerprint_digest,status,inventory_phase,created_at "
            "FROM crawl_runs"
        ).fetchone()
        new_run_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO crawl_runs VALUES (?,?,?,?,?,?)",
            (new_run_id, new_run_id, digest, status, phase, created_at),
        )
        db.execute(
            "INSERT INTO include_roots SELECT ?,include_root_ordinal,include_root_page_id "
            "FROM include_roots WHERE run_id=?",
            (new_run_id, run_id),
        )
        db.execute(
            "INSERT INTO root_progress SELECT ?,include_root_ordinal,progress,next_start,descendants_complete "
            "FROM root_progress WHERE run_id=?",
            (new_run_id, run_id),
        )
        session_id, started_at, ended_at, outcome_status, outcome_reason = db.execute(
            "SELECT session_id,started_at,ended_at,outcome_status,outcome_reason "
            "FROM crawl_sessions WHERE run_id=?",
            (run_id,),
        ).fetchone()
        db.execute(
            "INSERT INTO crawl_sessions VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), new_run_id, "paused", started_at, ended_at, outcome_status, outcome_reason),
        )
        db.commit()

    before = _snapshot(workspace)
    with SqliteConfluenceCheckpointRunPort().resume_unique_incomplete_run(
        _request(workspace, ResumeUniqueIncompleteRunRequest)
    ) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_match_ambiguous"
    assert _snapshot(workspace) == before


def _root_commit(activation):
    root_id = activation.snapshot.include_roots.root_ids[0]
    metadata = ConfluencePageMetadata(root_id, "Root", "SPACE")
    return InventoryRootCommit(
        activation.snapshot.run_id,
        0,
        root_id,
        metadata,
        activation.snapshot.include_roots,
    )


def _window_commit(activation, start, page_ids, total_size):
    root_id = activation.snapshot.include_roots.root_ids[0]
    items = tuple(
        ConfluencePageMetadata(page_id, page_id, "SPACE", root_id, (root_id,), ("Root",))
        for page_id in page_ids
    )
    window = ConfluenceInventoryWindow(items, start, 50, len(items), total_size)
    occurrences = tuple(
        InventoryOccurrence(
            activation.snapshot.run_id,
            0,
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
        0,
        root_id,
        start,
        window,
        occurrences,
        activation.snapshot.include_roots,
    )


def test_window_cap_denies_before_next_request(tmp_path):
    workspace = tmp_path / "window-cap"
    workspace.mkdir()
    trace = []
    request = _request(workspace)
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_windows_per_root=1, max_windows_per_run=10
        )
        activation.load_next_inventory_work()
        root_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "root", None, root_reservation.reservation_sequence))
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        window_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "window", 0, window_reservation.reservation_sequence))
        assert not isinstance(activation.commit_inventory_window(_window_commit(activation, 0, ("1001",), 2)), CheckpointOperationFailure)
        before_denied = _snapshot(workspace)
        denied = activation.load_next_inventory_work()
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
        before = _snapshot(workspace)
        denied_again = activation.load_next_inventory_work()
        assert isinstance(denied_again, CheckpointOperationFailure)
        _assert_same_except_reservations(before, _snapshot(workspace))
        _assert_same_except_reservations(before_denied, _snapshot(workspace))
    assert trace == [("request", "root", None, 0), ("request", "window", 0, 1)]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM inventory_windows").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM request_budget_reservations").fetchone() == (2,)
        assert db.execute(
            "SELECT progress,next_start FROM root_progress"
        ).fetchone() == ("descendants_pending", 1)
        assert db.execute("SELECT COUNT(*) FROM checkpoint_transitions").fetchone() == (3,)


def test_page_cap_denial_is_atomic_and_duplicate_ids_count_once(tmp_path):
    workspace = tmp_path / "page-cap"
    workspace.mkdir()
    trace = []
    request = _request(workspace)
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_pages_per_run=2, max_windows_per_root=10
        )
        activation.load_next_inventory_work()
        root_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "root", None, root_reservation.reservation_sequence))
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        first_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "window", 0, first_reservation.reservation_sequence))
        first_window = _window_commit(activation, 0, ("1001",), 3)
        assert not isinstance(activation.commit_inventory_window(first_window), CheckpointOperationFailure)
        activation.load_next_inventory_work()
        second_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "window", 1, second_reservation.reservation_sequence))
        duplicate_only = _window_commit(activation, 1, ("1001",), 3)
        assert not isinstance(activation.commit_inventory_window(duplicate_only), CheckpointOperationFailure)
        activation.load_next_inventory_work()
        third_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "window", 2, third_reservation.reservation_sequence))
        before_denied = _snapshot(workspace)
        denied = activation.commit_inventory_window(_window_commit(activation, 2, ("1002",), 3))
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.INVENTORY_PAGE_BUDGET_EXHAUSTED
        _assert_same_except_reservations(before_denied, _snapshot(workspace))
    assert trace == [
        ("request", "root", None, 0),
        ("request", "window", 0, 1),
        ("request", "window", 1, 2),
        ("request", "window", 2, 3),
    ]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM inventory_windows").fetchone() == (2,)
        assert db.execute("SELECT COUNT(*) FROM inventory_occurrences").fetchone() == (2,)
        assert db.execute(
            "SELECT progress,next_start FROM root_progress"
        ).fetchone() == ("descendants_pending", 2)
        assert db.execute("SELECT COUNT(*) FROM checkpoint_transitions").fetchone() == (4,)
        assert db.execute("SELECT COUNT(*) FROM request_budget_reservations").fetchone() == (4,)


def test_run_window_cap_denies_before_next_request(tmp_path):
    workspace = tmp_path / "run-window-cap"
    workspace.mkdir()
    trace = []
    request = _request(workspace)
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_windows_per_root=10, max_windows_per_run=1
        )
        activation.load_next_inventory_work()
        root_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "root", None, root_reservation.reservation_sequence))
        activation.commit_root_occurrence(_root_commit(activation))
        activation.load_next_inventory_work()
        window_reservation = activation.reserve_outbound_attempt()
        trace.append(("request", "window", 0, window_reservation.reservation_sequence))
        assert not isinstance(
            activation.commit_inventory_window(_window_commit(activation, 0, ("1001",), 2)),
            CheckpointOperationFailure,
        )
        before_denied = _snapshot(workspace)
        denied = activation.load_next_inventory_work()
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED
        assert isinstance(activation.load_next_inventory_work(), CheckpointOperationFailure)
        _assert_same_except_reservations(before_denied, _snapshot(workspace))
    assert trace == [("request", "root", None, 0), ("request", "window", 0, 1)]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM inventory_windows").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM request_budget_reservations").fetchone() == (2,)


def test_request_budget_cap_has_no_extra_reservation(tmp_path):
    workspace = tmp_path / "request-cap"
    workspace.mkdir()
    request = _request(workspace)
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation._state._limits = replace(activation._state._limits, max_total_requests_per_run=2)
        probe = _RequestProbe(activation)
        assert probe.request().reservation_sequence == 0
        assert probe.request().reservation_sequence == 1
        denied = probe.request()
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED
        assert probe.calls == 2
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM request_budget_reservations").fetchone() == (2,)
