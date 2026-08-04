"""Tracked M7-C5 inventory acceptance composition over the approved seams."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import replace
from email.message import Message
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopController,
    ControlledStopPolicy,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    InventoryRootCommit,
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
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _RunRegistryRequest,
    _register_checkpoint_run,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)

from test_m7_c5b_scale_baseline import _run_child
from knowledgenexus.foundation.infrastructure.checkpoint import (
    sqlite_checkpoint_workspace as workspace_module,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_inventory_adapter import (
    ConfluenceDataCenterRequestError,
    ConfluenceDataCenterInventoryAdapter,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_retrying_http_transport import (
    ConfluenceRetryExecutorProfile,
    RetryingConfluenceHttpTransport,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
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


class InjectedAfterResponse(RuntimeError):
    pass


class InjectedBeforeIo(RuntimeError):
    pass


class InjectedAfterAcknowledgement(RuntimeError):
    pass


class _FakeClock:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self._events = events

    def __call__(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self._events.append(("sleep", duration))
        self.now += duration


class _FakeResponse:
    def __init__(self, *, status: int, body: bytes, retry_after: str | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = Message()
        if status == 200:
            self.headers["Content-Type"] = "application/json"
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _ScriptedOpener:
    """Synthetic B1 opener; start=0 alternates 429/200 per logical call."""

    def __init__(self, *, fail_before_io_once: bool = False) -> None:
        self.calls: list[tuple[str, str | None, int]] = []
        self.events: list[tuple[object, ...]] = []
        self._attempts: dict[tuple[str, str | None], int] = {}
        self._fail_before_io_once = fail_before_io_once

    def open(self, request: object, *, timeout: float) -> _FakeResponse:
        del timeout
        parsed = urllib.parse.urlsplit(getattr(request, "full_url"))
        query = urllib.parse.parse_qs(parsed.query)
        start = query.get("start", [None])[0]
        key = (parsed.path, start)
        if self._fail_before_io_once:
            self._fail_before_io_once = False
            raise InjectedBeforeIo()
        attempt = self._attempts.get(key, 0)
        self._attempts[key] = attempt + 1

        if parsed.path.endswith("/content/1000"):
            status, body, retry_after = 200, _root_payload(), None
        elif start == "0" and attempt % 2 == 0:
            status, body, retry_after = 429, b"{}", "1"
        elif start == "0":
            status, body, retry_after = 200, _window_payload(0), None
        elif start == "1":
            status, body, retry_after = 200, _window_payload(1), None
        else:
            raise AssertionError("unexpected synthetic request")

        self.calls.append((parsed.path, start, status))
        self.events.append(("request", parsed.path, start, status))
        return _FakeResponse(status=status, body=body, retry_after=retry_after)


class _ReservationProbe:
    def __init__(self, activation, events: list[tuple[object, ...]]) -> None:
        self._activation = activation
        self._events = events

    def reserve_outbound_attempt(self):
        result = self._activation.reserve_outbound_attempt()
        self._events.append(("reservation", getattr(result, "reservation_sequence", "denied")))
        return result

    def check_outbound_attempt(self):
        return self._activation.check_outbound_attempt()


class _FaultingWindowPort:
    def __init__(self, inner: ConfluenceDataCenterInventoryAdapter, fault: list[bool]) -> None:
        self._inner = inner
        self._fault = fault

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str):
        return self._inner.fetch_root_metadata(space_key=space_key, root_page_id=root_page_id)

    def fetch_descendants_window(
        self, *, space_key: str, root_page_id: str, start: int, page_size: int
    ):
        window = self._inner.fetch_descendants_window(
            space_key=space_key,
            root_page_id=root_page_id,
            start=start,
            page_size=page_size,
        )
        if start == 0 and not self._fault[0]:
            self._fault[0] = True
            raise InjectedAfterResponse()
        return window


def _root_payload() -> bytes:
    return json.dumps(
        {
            "id": "1000",
            "status": "current",
            "title": "Fixture Root",
            "type": "page",
            "space": {"key": "SPACE"},
            "version": {"number": 1, "when": "2000-01-01T00:00:00.000+00:00"},
        },
        sort_keys=True,
    ).encode("utf-8")


def _window_payload(start: int) -> bytes:
    page_id = str(1001 + start)
    item = {
        "content": {
            "id": page_id,
            "status": "current",
            "title": f"Fixture Page {page_id}",
            "type": "page",
            "space": {"key": "SPACE"},
            "ancestors": [{"id": "1000", "title": "Fixture Root"}],
            "version": {"number": 1, "when": "2000-01-01T00:00:00.000+00:00"},
            "metadata": {
                "labels": {
                    "_links": {"self": "/synthetic-labels"},
                    "results": [],
                    "size": 0,
                    "start": 0,
                    "limit": 200,
                }
            },
        }
    }
    return json.dumps(
        {"limit": 50, "results": [item], "size": 1, "start": start, "totalSize": 2},
        sort_keys=True,
    ).encode("utf-8")


def _request(workspace: Path, request_type=StartNewRunRequest, run_id=None):
    config = ConfluenceSourceConfig(
        "synthetic", "SPACE", (ConfluenceIncludeRoot("1000"),), page_size=50
    )
    if request_type is ResumeUniqueIncompleteRunRequest:
        return request_type(workspace, "https://fixture.invalid/confluence", config, PROFILE)
    return request_type(workspace, "https://fixture.invalid/confluence", config, PROFILE)


def _build_use_case(
    opener: _ScriptedOpener,
    timing: _FakeClock,
    fault: list[bool] | None = None,
    *,
    deny_budget: bool = False,
):
    def transport_factory(activation):
        if deny_budget:
            private_activation = activation._resolve()
            private_activation._state._limits = replace(
                private_activation._state._limits,
                max_total_requests_per_run=0,
            )
        reserver = _ReservationProbe(activation, opener.events)
        inner = UrllibConfluenceHttpTransport(
            base_url="https://fixture.invalid/confluence",
            personal_access_token="synthetic-test-token",
            timeout_seconds=1.0,
            max_response_bytes=8388608,
        )
        return RetryingConfluenceHttpTransport(
            inner=inner,
            profile=ConfluenceRetryExecutorProfile.from_mapping(PROFILE),
            monotonic_clock=timing,
            sleeper=timing.sleep,
            attempt_reserver=reserver,
        )

    def window_factory(transport):
        adapter = ConfluenceDataCenterInventoryAdapter(transport=transport, max_search_pages=4)
        return _FaultingWindowPort(adapter, fault) if fault is not None else adapter

    return ExecuteDurableConfluenceInventory(
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        inventory_transport_factory=transport_factory,
        inventory_window_port_factory=window_factory,
    )


def _durable_snapshot(workspace: Path) -> dict[str, object]:
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        return {
            "windows": db.execute(
                "SELECT requested_start,observed_start,response_size,total_size,next_start,terminal "
                "FROM inventory_windows ORDER BY requested_start"
            ).fetchall(),
            "occurrences": db.execute(
                "SELECT page_id,window_start,item_ordinal FROM inventory_occurrences "
                "ORDER BY window_start,item_ordinal"
            ).fetchall(),
            "transitions": db.execute(
                "SELECT sequence,from_progress,to_progress FROM checkpoint_transitions ORDER BY sequence"
            ).fetchall(),
            "sessions": db.execute(
                "SELECT status,outcome_status,outcome_reason FROM crawl_sessions "
                "ORDER BY started_at,session_id"
            ).fetchall(),
        }


def _registry_request(request):
    return _RunRegistryRequest(
        request.workspace,
        StartNewRun(),
        request.endpoint_url,
        request.source_config,
        request.reliability_profile,
    )


def _root_commit_for(activation, ordinal: int, root_id: str):
    metadata = ConfluencePageMetadata(root_id, f"Root {root_id}", "SPACE")
    return InventoryRootCommit(
        activation.snapshot.run_id,
        ordinal,
        root_id,
        metadata,
        activation.snapshot.include_roots,
    )


def _window_commit_for(
    activation,
    *,
    ordinal: int,
    root_id: str,
    start: int,
    page_id: str,
    total_size: int,
    ancestors: tuple[str, ...] | None = None,
):
    ancestor_ids = ancestors or (root_id,)
    metadata = ConfluencePageMetadata(
        page_id,
        f"Page {page_id}",
        "SPACE",
        ancestor_ids[-1],
        ancestor_ids,
        tuple(f"Page {value}" for value in ancestor_ids),
    )
    window = ConfluenceInventoryWindow((metadata,), start, 50, 1, total_size)
    occurrence = InventoryOccurrence(
        activation.snapshot.run_id,
        ordinal,
        root_id,
        start,
        0,
        page_id,
        metadata,
        activation.snapshot.include_roots,
    )
    return InventoryWindowCommit(
        activation.snapshot.run_id,
        ordinal,
        root_id,
        start,
        window,
        (occurrence,),
        activation.snapshot.include_roots,
    )


def test_include_root_cap_accepts_exact_limit_and_rejects_cap_plus_one(tmp_path):
    exact_workspace = tmp_path / "exact"
    exact_workspace.mkdir()
    exact = _request(exact_workspace)
    exact_config = replace(
        exact.source_config,
        include_roots=tuple(ConfluenceIncludeRoot(str(1000 + index)) for index in range(16)),
    )
    exact = replace(exact, source_config=exact_config)
    with _register_checkpoint_run(_registry_request(exact)) as activation:
        assert len(activation.snapshot.include_roots.root_ids) == 16
    assert (exact_workspace / "crawl_state.sqlite3").exists()

    overflow_workspace = tmp_path / "overflow"
    overflow_workspace.mkdir()
    with pytest.raises(ValueError):
        overflow = replace(
            _request(overflow_workspace),
            source_config=replace(
                _request(overflow_workspace).source_config,
                include_roots=tuple(
                    ConfluenceIncludeRoot(str(1000 + index)) for index in range(17)
                ),
            ),
        )
    assert not (overflow_workspace / "crawl_state.sqlite3").exists()
    assert not (overflow_workspace / "crawl_writer.lock").exists()


def test_cross_root_duplicate_id_is_stored_per_occurrence_but_counted_once(tmp_path):
    workspace = tmp_path / "cross-root"
    workspace.mkdir()
    request = _request(workspace)
    request = replace(
        request,
        source_config=replace(
            request.source_config,
            include_roots=(ConfluenceIncludeRoot("1000"), ConfluenceIncludeRoot("2000")),
        ),
    )
    with _register_checkpoint_run(_registry_request(request)) as activation:
        assert activation.load_next_inventory_work().kind == "root"
        activation.commit_root_occurrence(_root_commit_for(activation, 0, "1000"))
        activation.load_next_inventory_work()
        assert not isinstance(
            activation.commit_inventory_window(
                _window_commit_for(
                    activation,
                    ordinal=0,
                    root_id="1000",
                    start=0,
                    page_id="3000",
                    total_size=1,
                )
            ),
            Exception,
        )
        assert activation.load_next_inventory_work().kind == "root"
        activation.commit_root_occurrence(_root_commit_for(activation, 1, "2000"))
        activation.load_next_inventory_work()
        activation.commit_inventory_window(
            _window_commit_for(
                activation,
                ordinal=1,
                root_id="2000",
                start=0,
                page_id="3000",
                total_size=1,
            )
        )
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT page_id) FROM inventory_occurrences"
        ).fetchone() == (2, 1)


def test_excluded_descendant_still_consumes_durable_unique_page_budget(tmp_path):
    workspace = tmp_path / "excluded-budget"
    workspace.mkdir()
    request = _request(workspace)
    request = replace(
        request,
        source_config=replace(
            request.source_config,
            exclude_subtrees=(ConfluenceExcludeSubtree("4000"),),
        ),
    )
    with _register_checkpoint_run(_registry_request(request)) as activation:
        activation._state._limits = replace(activation._state._limits, max_pages_per_run=2)
        activation.load_next_inventory_work()
        activation.commit_root_occurrence(_root_commit_for(activation, 0, "1000"))
        activation.load_next_inventory_work()
        first = activation.commit_inventory_window(
            _window_commit_for(
                activation,
                ordinal=0,
                root_id="1000",
                start=0,
                page_id="4001",
                total_size=2,
                ancestors=("1000", "4000"),
            )
        )
        assert not isinstance(first, Exception)
        activation.load_next_inventory_work()
        denied = activation.commit_inventory_window(
            _window_commit_for(
                activation,
                ordinal=0,
                root_id="1000",
                start=1,
                page_id="4002",
                total_size=2,
                ancestors=("1000", "4000"),
            )
        )
        assert getattr(denied, "category", None).value == "inventory_page_budget_exhausted"
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT page_id FROM inventory_occurrences"
        ).fetchall() == [("4001",)]


@pytest.mark.parametrize("fault_mode", ["before_transaction", "after_rows_before_cursor"])
def test_inventory_transaction_faults_rollback_without_cursor_advance(
    tmp_path, monkeypatch, fault_mode
):
    workspace = tmp_path / fault_mode
    workspace.mkdir()
    request = _request(workspace)
    transaction_type = workspace_module._PrivateCheckpointTransaction
    original_begin = transaction_type._begin_immediate
    original_execute = transaction_type._execute
    armed = [False]

    def begin_fault(transaction):
        if armed[0] and fault_mode == "before_transaction":
            raise RuntimeError("injected begin fault")
        return original_begin(transaction)

    def execute_fault(transaction, sql, parameters=()):
        if armed[0] and fault_mode == "after_rows_before_cursor" and "UPDATE root_progress" in sql:
            raise RuntimeError("injected cursor fault")
        return original_execute(transaction, sql, parameters)

    monkeypatch.setattr(transaction_type, "_begin_immediate", begin_fault)
    monkeypatch.setattr(transaction_type, "_execute", execute_fault)
    with pytest.raises(CheckpointStateError):
        with _register_checkpoint_run(_registry_request(request)) as activation:
            activation.load_next_inventory_work()
            activation.commit_root_occurrence(_root_commit_for(activation, 0, "1000"))
            activation.load_next_inventory_work()
            armed[0] = True
            activation.commit_inventory_window(
                _window_commit_for(
                    activation,
                    ordinal=0,
                    root_id="1000",
                    start=0,
                    page_id="1001",
                    total_size=1,
                )
            )
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM inventory_windows").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM inventory_occurrences").fetchone() == (0,)
        assert db.execute(
            "SELECT progress,next_start FROM root_progress"
        ).fetchone() == ("descendants_pending", 0)


def test_integrated_retry_pacing_reservation_and_exact_inventory(tmp_path, monkeypatch):
    opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    timing = _FakeClock(opener.events)
    result = _build_use_case(opener, timing).execute(request=_request(tmp_path))

    assert result.status == "completed"
    assert opener.calls == [
        ("/confluence/rest/api/content/1000", None, 200),
        ("/confluence/rest/api/search", "0", 429),
        ("/confluence/rest/api/search", "0", 200),
        ("/confluence/rest/api/search", "1", 200),
    ]
    assert len(timing.sleeps) == 3
    reservation_events = [index for index, event in enumerate(opener.events) if event[0] == "reservation"]
    request_events = [index for index, event in enumerate(opener.events) if event[0] == "request"]
    assert len(reservation_events) == len(request_events) == 4
    assert all(
        reservation + 1 == request
        for reservation, request in zip(reservation_events, request_events)
    )
    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT page_id FROM (SELECT page_id FROM root_occurrences UNION ALL "
            "SELECT page_id FROM inventory_occurrences) ORDER BY CAST(page_id AS INTEGER)"
        ).fetchall() == [("1000",), ("1001",), ("1002",)]
        assert db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT page_id) FROM inventory_occurrences"
        ).fetchone() == (2, 2)
        assert db.execute(
            "SELECT COUNT(*) FROM request_budget_reservations"
        ).fetchone() == (4,)


def test_after_response_resume_consumes_reservation_and_matches_uninterrupted(tmp_path, monkeypatch):
    full_workspace = tmp_path / "full"
    full_workspace.mkdir()
    full_opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: full_opener)
    full_timing = _FakeClock(full_opener.events)
    full = _build_use_case(full_opener, full_timing).execute(request=_request(full_workspace))
    assert full.status == "completed"
    full_state = _durable_snapshot(full_workspace)

    resumed_workspace = tmp_path / "resumed"
    resumed_workspace.mkdir()
    resumed_opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: resumed_opener)
    resumed_timing = _FakeClock(resumed_opener.events)
    fault = [False]
    with pytest.raises(InjectedAfterResponse):
        _build_use_case(resumed_opener, resumed_timing, fault).execute(
            request=_request(resumed_workspace)
        )
    assert resumed_opener.calls == [
        ("/confluence/rest/api/content/1000", None, 200),
        ("/confluence/rest/api/search", "0", 429),
        ("/confluence/rest/api/search", "0", 200),
    ]
    resumed = _build_use_case(resumed_opener, resumed_timing, fault).execute(
        request=_request(resumed_workspace, ResumeUniqueIncompleteRunRequest)
    )
    assert resumed.status == "completed"
    assert _durable_snapshot(resumed_workspace)["windows"] == full_state["windows"]
    assert _durable_snapshot(resumed_workspace)["occurrences"] == full_state["occurrences"]
    assert _durable_snapshot(resumed_workspace)["transitions"] == full_state["transitions"]
    with sqlite3.connect(resumed_workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT COUNT(*) FROM request_budget_reservations"
        ).fetchone() == (6,)
        assert db.execute(
            "SELECT page_id FROM (SELECT page_id FROM root_occurrences UNION ALL "
            "SELECT page_id FROM inventory_occurrences) ORDER BY CAST(page_id AS INTEGER)"
        ).fetchall() == [("1000",), ("1001",), ("1002",)]


def test_controlled_stop_pauses_before_next_request_and_resumes_cleanly(tmp_path, monkeypatch):
    opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    timing = _FakeClock(opener.events)
    use_case = _build_use_case(opener, timing)
    paused = use_case.execute(
        request=_request(tmp_path),
        controlled_stop_policy=ControlledStopPolicy(1),
    )
    assert paused.status == "paused"
    assert opener.calls == [
        ("/confluence/rest/api/content/1000", None, 200),
        ("/confluence/rest/api/search", "0", 429),
        ("/confluence/rest/api/search", "0", 200),
    ]
    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions"
        ).fetchall() == [("paused", "paused", "controlled_checkpoint_stop")]
        assert db.execute(
            "SELECT COUNT(*) FROM inventory_windows"
        ).fetchone() == (1,)
    resumed = use_case.execute(
        request=_request(tmp_path, ResumeUniqueIncompleteRunRequest)
    )
    assert resumed.status == "completed"
    assert _durable_snapshot(tmp_path)["windows"] == [(0, 0, 1, 2, 1, 0), (1, 1, 1, 2, 2, 1)]


def test_after_reservation_before_io_consumes_budget_across_resume(tmp_path, monkeypatch):
    opener = _ScriptedOpener(fail_before_io_once=True)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    timing = _FakeClock(opener.events)
    with pytest.raises(InjectedBeforeIo):
        _build_use_case(opener, timing).execute(request=_request(tmp_path))
    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT COUNT(*) FROM request_budget_reservations"
        ).fetchone() == (1,)
    resumed = _build_use_case(opener, timing).execute(
        request=_request(tmp_path, ResumeUniqueIncompleteRunRequest)
    )
    assert resumed.status == "completed"
    assert opener.calls[0] == ("/confluence/rest/api/content/1000", None, 200)
    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT COUNT(*) FROM request_budget_reservations"
        ).fetchone() == (5,)


def test_after_commit_before_acknowledgement_replays_without_duplicate_transition(
    tmp_path, monkeypatch
):
    full_workspace = tmp_path / "full"
    full_workspace.mkdir()
    full_opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: full_opener)
    full_timing = _FakeClock(full_opener.events)
    full = _build_use_case(full_opener, full_timing).execute(request=_request(full_workspace))
    assert full.status == "completed"
    full_state = _durable_snapshot(full_workspace)

    workspace = tmp_path / "ack"
    workspace.mkdir()
    opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    timing = _FakeClock(opener.events)
    original_record = ControlledStopController.record
    fired = [False]

    def fail_once(controller, result):
        if not fired[0]:
            fired[0] = True
            raise InjectedAfterAcknowledgement()
        return original_record(controller, result)

    monkeypatch.setattr(ControlledStopController, "record", fail_once)
    with pytest.raises(InjectedAfterAcknowledgement):
        _build_use_case(opener, timing).execute(request=_request(workspace))
    resumed = _build_use_case(opener, timing).execute(
        request=_request(workspace, ResumeUniqueIncompleteRunRequest)
    )
    assert resumed.status == "completed"
    state = _durable_snapshot(workspace)
    assert state["windows"] == full_state["windows"]
    assert state["occurrences"] == full_state["occurrences"]
    assert state["transitions"] == full_state["transitions"]
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute(
            "SELECT COUNT(*) FROM checkpoint_transitions"
        ).fetchone() == (4,)
        assert db.execute(
            "SELECT COUNT(*) FROM request_budget_reservations"
        ).fetchone() == (4,)


def test_denied_budget_starts_no_request_or_retry_sleep(tmp_path, monkeypatch):
    opener = _ScriptedOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    timing = _FakeClock(opener.events)
    use_case = _build_use_case(opener, timing, deny_budget=True)
    with pytest.raises(ConfluenceDataCenterRequestError) as captured:
        use_case.execute(request=_request(tmp_path))
    assert captured.value.__cause__ is not None
    assert captured.value.__cause__.decision.outcome_class.value == "budget_exhausted"
    assert opener.calls == []
    assert timing.sleeps == []


def test_tracked_functional_10k_gate_is_opt_in(tmp_path):
    if os.environ.get("KNOWLEDGENEXUS_RUN_10K") != "1":
        pytest.skip("opt-in tracked 10k functional correctness gate")
    result = _run_child(tmp_path / "functional-10k", 10000)
    assert result["status"] == "completed"
    assert result["page_count"] == 10000
    assert result["window_count"] == 200
    assert result["request_count"] == 201
    assert result["reservation_count"] == 201
    assert result["transition_count"] == 202
    assert result["max_window_items"] == 50
    assert result["deterministic_result"] == "validated"
