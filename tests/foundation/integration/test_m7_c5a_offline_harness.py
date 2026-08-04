from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopPolicy,
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
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunSelectionFailure,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
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


class InjectedCrash(RuntimeError):
    pass


@dataclass
class FaultInjector:
    point: str | None = None
    fired: bool = False

    def fire(self, point: str) -> None:
        if self.point == point and not self.fired:
            self.fired = True
            raise InjectedCrash(point)


class ScriptedWindowPort:
    def __init__(self, activation, trace, fault: FaultInjector | None = None):
        self.activation = activation
        self.trace = trace
        self.fault = fault or FaultInjector()

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str):
        reservation = self.activation.reserve_outbound_attempt()
        self.trace.append(("reservation", reservation.reservation_sequence))
        self.trace.append(("request", "root", None))
        self.fault.fire("after_reservation")
        return ConfluencePageMetadata(root_page_id, "Root", space_key)

    def fetch_descendants_window(
        self, *, space_key: str, root_page_id: str, start: int, page_size: int
    ):
        reservation = self.activation.reserve_outbound_attempt()
        self.trace.append(("reservation", reservation.reservation_sequence))
        self.trace.append(("request", "window", start))
        self.fault.fire("after_reservation")
        self.fault.fire("after_response")
        if start == 0:
            items = (ConfluencePageMetadata("1001", "Child 1", space_key, root_page_id, (root_page_id,), ("Root",)),)
            return ConfluenceInventoryWindow(items, 0, page_size, 1, 2)
        items = (ConfluencePageMetadata("1002", "Child 2", space_key, root_page_id, (root_page_id,), ("Root",)),)
        return ConfluenceInventoryWindow(items, 1, page_size, 1, 2)


def _request(workspace: Path, kind=StartNewRunRequest, run_id=None):
    config = ConfluenceSourceConfig(
        "synthetic", "SPACE", (ConfluenceIncludeRoot("1000"),), page_size=50
    )
    if kind is ResumeExplicitRunRequest:
        return kind(workspace, run_id, "https://fixture.invalid/confluence", config, PROFILE)
    return kind(workspace, "https://fixture.invalid/confluence", config, PROFILE)


def _use_case(trace, fault=None):
    def factory(activation):
        return ScriptedWindowPort(activation, trace, fault)

    return ExecuteDurableConfluenceInventory(
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        inventory_transport_factory=lambda activation: activation,
        inventory_window_port_factory=factory,
    )


def _rows(workspace: Path):
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        return {
            "windows": db.execute("SELECT requested_start,observed_start,response_size,total_size,next_start,terminal FROM inventory_windows ORDER BY requested_start").fetchall(),
            "occurrences": db.execute("SELECT page_id,window_start,item_ordinal FROM inventory_occurrences ORDER BY window_start,item_ordinal").fetchall(),
            "transitions": db.execute("SELECT sequence,from_progress,to_progress FROM checkpoint_transitions ORDER BY sequence").fetchall(),
        }


def _canonical_trace(workspace: Path, request_trace):
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        transitions = db.execute(
            "SELECT sequence,from_progress,to_progress FROM checkpoint_transitions "
            "ORDER BY sequence"
        ).fetchall()
        occurrences = db.execute(
            "SELECT window_start,item_ordinal,page_id FROM inventory_occurrences "
            "ORDER BY window_start,item_ordinal"
        ).fetchall()
        sessions = db.execute(
            "SELECT status,outcome_reason FROM crawl_sessions "
            "ORDER BY started_at,session_id"
        ).fetchall()
    return (
        tuple(request_trace),
        tuple(("transition", *row) for row in transitions),
        tuple(("occurrence", *row) for row in occurrences),
        tuple(("session", *row) for row in sessions),
    )


def test_c5a_uninterrupted_and_after_response_resume_have_same_durable_rows(tmp_path):
    uninterrupted_trace = []
    uninterrupted = _use_case(uninterrupted_trace)
    full_workspace = tmp_path / "full"
    full_workspace.mkdir()
    assert uninterrupted.execute(request=_request(full_workspace)).status == "completed"
    assert uninterrupted_trace == [
        ("reservation", 0),
        ("request", "root", None),
        ("reservation", 1),
        ("request", "window", 0),
        ("reservation", 2),
        ("request", "window", 1),
    ]

    resumed_trace = []
    fault = FaultInjector("after_response")
    workspace = tmp_path / "resumed"
    workspace.mkdir()
    with pytest.raises(InjectedCrash):
        _use_case(resumed_trace, fault).execute(request=_request(workspace))
    paused = _use_case(resumed_trace).execute(
        request=_request(workspace, ResumeUniqueIncompleteRunRequest)
    )
    assert paused.status == "completed"
    assert _rows(workspace) == _rows(full_workspace)
    assert _canonical_trace(workspace, resumed_trace)[1:3] == _canonical_trace(
        full_workspace, uninterrupted_trace
    )[1:3]
    assert resumed_trace == [
        ("reservation", 0),
        ("request", "root", None),
        ("reservation", 1),
        ("request", "window", 0),
        ("reservation", 2),
        ("request", "window", 0),
        ("reservation", 3),
        ("request", "window", 1),
    ]
    assert resumed_trace[-1] == ("request", "window", 1)
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT reservation_sequence FROM request_budget_reservations "
            "ORDER BY reservation_sequence"
        ).fetchall() == [(0,), (1,), (2,), (3,)]
        assert db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions "
            "ORDER BY started_at,session_id"
        ).fetchall() == [
            ("interrupted", "interrupted", "process_interrupted"),
            ("completed", "completed", "completed"),
        ]


def test_c5a1_session_finalizers_reject_stale_activation_without_mutation(tmp_path):
    workspace = tmp_path / "stale"
    workspace.mkdir()
    port = SqliteConfluenceCheckpointRunPort()
    request = _request(workspace)
    with port.start_new_run(request) as outcome:
        outcome.complete_session()
        with pytest.raises(CheckpointStateError):
            outcome.complete_session()
        with pytest.raises(CheckpointStateError):
            outcome.pause_session()
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions"
        ).fetchall() == [("completed", "completed", "completed")]


def test_c5a1_controlled_stop_persists_pause_and_resumes(tmp_path):
    baseline_workspace = tmp_path / "baseline"
    baseline_workspace.mkdir()
    baseline_trace = []
    assert _use_case(baseline_trace).execute(
        request=_request(baseline_workspace)
    ).status == "completed"
    workspace = tmp_path / "paused"
    workspace.mkdir()
    trace = []
    result = _use_case(trace).execute(
        request=_request(workspace), controlled_stop_policy=ControlledStopPolicy(1)
    )
    assert result.status == "paused"
    assert trace == [
        ("reservation", 0),
        ("request", "root", None),
        ("reservation", 1),
        ("request", "window", 0),
    ]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions"
        ).fetchall() == [("paused", "paused", "controlled_checkpoint_stop")]
        assert db.execute(
            "SELECT COUNT(*) FROM crawl_sessions WHERE status='active'"
        ).fetchone() == (0,)
    resumed = _use_case(trace).execute(
        request=_request(workspace, ResumeUniqueIncompleteRunRequest)
    )
    assert resumed.status == "completed"
    assert _rows(workspace) == _rows(baseline_workspace)
    assert _canonical_trace(workspace, trace)[1:3] == _canonical_trace(
        baseline_workspace, baseline_trace
    )[1:3]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions "
            "ORDER BY started_at,session_id"
        ).fetchall() == [
            ("paused", "paused", "controlled_checkpoint_stop"),
            ("completed", "completed", "completed"),
        ]


def test_c5a_selection_failures_are_typed_and_nonmutating(tmp_path):
    port = SqliteConfluenceCheckpointRunPort()
    missing_workspace = tmp_path / "missing"
    missing_workspace.mkdir()
    missing = _request(missing_workspace, ResumeUniqueIncompleteRunRequest)
    with port.resume_unique_incomplete_run(missing) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_not_found"

    workspace = tmp_path / "conflict"
    workspace.mkdir()
    trace = []
    assert _use_case(trace).execute(request=_request(workspace)).status == "completed"
    with port.start_new_run(_request(workspace)) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "incomplete_run_conflict"
