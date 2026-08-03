from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import platform
import sys
import time
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
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
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)


PROFILE_V1 = {
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
PROFILE_V2 = dict(
    PROFILE_V1,
    profile_id="m7-crawl-scale-acceptance-v2",
    profile_version="2",
    max_pages_per_run=100000,
    max_inventory_windows_per_root=2000,
)


def _request(workspace: Path, page_count: int, resume: bool = False):
    profile = PROFILE_V2 if page_count == 100000 else PROFILE_V1
    config = ConfluenceSourceConfig(
        "synthetic-scale",
        "SPACE",
        (ConfluenceIncludeRoot("1000"),),
        page_size=50,
    )
    request_type = ResumeUniqueIncompleteRunRequest if resume else StartNewRunRequest
    return request_type(
        workspace,
        "https://fixture.invalid/confluence",
        config,
        profile,
    )


class _GeneratedScalePort:
    def __init__(self, total_pages: int, trace: list[int], activation) -> None:
        self._total_descendants = total_pages - 1
        self._trace = trace
        self._activation = activation
        self.max_window_items = 0

    def _reserve(self, start: int | None) -> None:
        result = self._activation.reserve_outbound_attempt()
        assert getattr(result, "reservation_sequence", None) is not None
        self._trace.append(-1 if start is None else start)

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str):
        self._reserve(None)
        return ConfluencePageMetadata(root_page_id, "Root", space_key)

    def fetch_descendants_window(
        self, *, space_key: str, root_page_id: str, start: int, page_size: int
    ) -> ConfluenceInventoryWindow:
        self._reserve(start)
        count = min(page_size, self._total_descendants - start)
        self.max_window_items = max(self.max_window_items, count)
        items = tuple(
            ConfluencePageMetadata(
                str(1001 + start + ordinal),
                f"Page {start + ordinal}",
                space_key,
                root_page_id,
                (root_page_id,),
                ("Root",),
            )
            for ordinal in range(count)
        )
        return ConfluenceInventoryWindow(items, start, page_size, count, self._total_descendants)


def _child_workload(workspace: str, page_count: int, control) -> None:
    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)
    traces: list[int] = []
    transport_holder: list[_GeneratedScalePort] = []

    def transport_factory(activation):
        transport = _GeneratedScalePort(page_count, traces, activation)
        transport_holder.append(transport)
        return transport

    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        inventory_transport_factory=transport_factory,
        inventory_window_port_factory=lambda transport: transport,
    )
    control.send(("ready", None))
    command = control.recv()
    if command != ("start", None):
        control.send(("failed", "invalid control command"))
        return

    started = time.monotonic()
    result = use_case.execute(request=_request(workspace_path, page_count))
    elapsed = time.monotonic() - started
    if result.status != "completed":
        control.send(("failed", result.status))
        return

    # The resume path must not build a transport or mutate checkpoint state.
    before_resume_trace = tuple(traces)
    resumed = use_case.execute(request=_request(workspace_path, page_count, resume=True))
    if resumed.status != "inventory_complete" or tuple(traces) != before_resume_trace:
        control.send(("failed", "resume_not_idempotent"))
        return

    import sqlite3

    with sqlite3.connect(workspace_path / "crawl_state.sqlite3") as db:
        inventory = db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT page_id),MIN(CAST(page_id AS INTEGER)),"
            "MAX(CAST(page_id AS INTEGER)) "
            "FROM inventory_occurrences"
        ).fetchone()
        out_of_range = db.execute(
            "SELECT COUNT(*) FROM inventory_occurrences "
            "WHERE CAST(page_id AS INTEGER) < 1001 OR CAST(page_id AS INTEGER) > ?",
            (1000 + page_count - 1,),
        ).fetchone()[0]
        windows = db.execute("SELECT COUNT(*) FROM inventory_windows").fetchone()[0]
        transitions = db.execute("SELECT COUNT(*) FROM checkpoint_transitions").fetchone()[0]
        reservations = db.execute("SELECT COUNT(*) FROM request_budget_reservations").fetchone()[0]
        root_occurrences = db.execute("SELECT COUNT(*) FROM root_occurrences").fetchone()[0]
        sessions = db.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions"
        ).fetchall()

    expected_descendants = page_count - 1
    expected_windows = (expected_descendants + 49) // 50
    expected_requests = expected_windows + 1
    if inventory != (
        expected_descendants,
        expected_descendants,
        1001,
        1000 + expected_descendants,
    ):
        control.send(("failed", "inventory_identity_mismatch"))
        return
    if (
        windows != expected_windows
        or transitions != expected_windows + 2
        or reservations != expected_requests
        or root_occurrences != 1
        or sessions != [("completed", "completed", "completed")]
        or transport_holder[0].max_window_items > 50
        or out_of_range != 0
    ):
        control.send(("failed", "durable_count_mismatch"))
        return
    control.send(
        (
            "complete",
            {
                "status": "completed",
                "profile_id": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_id"],
                "profile_version": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_version"],
                "page_count": page_count,
                "descendant_count": expected_descendants,
                "window_count": expected_windows,
                "request_count": expected_requests,
                "transition_count": expected_windows + 2,
                "reservation_count": expected_requests,
                "max_window_items": transport_holder[0].max_window_items,
                "trace": traces,
                "elapsed_seconds": round(elapsed, 6),
                "deterministic_result": "validated",
            },
        )
    )


def _rss_bytes(pid: int) -> tuple[int | None, str]:
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None, "windows_unavailable"
        try:
            class _Counters(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("page_fault_count", ctypes.c_ulong),
                            ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
                            ("quota_peak_paged_pool", ctypes.c_size_t), ("quota_paged_pool", ctypes.c_size_t),
                            ("quota_peak_non_paged_pool", ctypes.c_size_t), ("quota_non_paged_pool", ctypes.c_size_t),
                            ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t)]
            counters = _Counters()
            counters.cb = ctypes.sizeof(counters)
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            return (int(counters.working_set), "windows") if ok else (None, "windows_unavailable")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE"), "linux"
        except (FileNotFoundError, IndexError, ValueError, OSError):
            return None, "linux_unavailable"
    return None, f"{sys.platform}_unsupported"


def _run_child(workspace: Path, page_count: int, interval: float = 0.1) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_child_workload, args=(str(workspace), page_count, child))
    started_at = time.monotonic()
    process.start()
    child.close()
    default_timeout = 1800 if page_count >= 100000 else 600
    timeout_override = os.environ.get("KNOWLEDGENEXUS_SCALE_TIMEOUT_SECONDS")
    try:
        timeout_seconds = float(timeout_override) if timeout_override else default_timeout
    except ValueError:
        timeout_seconds = default_timeout
    deadline = time.monotonic() + timeout_seconds
    if not parent.poll(30):
        process.terminate()
        process.join(10)
        raise AssertionError("scale child did not become ready")
    message, _ = parent.recv()
    assert message == "ready"
    baseline, observer = _rss_bytes(process.pid)
    parent.send(("start", None))
    peak = baseline
    result: dict[str, object] | None = None
    while time.monotonic() < deadline:
        if parent.poll(interval):
            kind, payload = parent.recv()
            if kind == "complete":
                result = payload
                break
            process.terminate()
            process.join(10)
            raise AssertionError(payload)
        current, _ = _rss_bytes(process.pid)
        if current is not None:
            peak = current if peak is None else max(peak, current)
    if result is None:
        process.terminate()
        process.join(10)
        import sqlite3

        counts = {"window_count": 0, "occurrence_count": 0}
        db_path = workspace / "crawl_state.sqlite3"
        if db_path.exists():
            with sqlite3.connect(db_path) as db:
                counts["window_count"] = db.execute(
                    "SELECT COUNT(*) FROM inventory_windows"
                ).fetchone()[0]
                counts["occurrence_count"] = db.execute(
                    "SELECT COUNT(*) FROM inventory_occurrences"
                ).fetchone()[0]
        (workspace / "m7-c5b-scale-timeout.json").write_text(
            json.dumps(
                {
                    "kind": "m7-c5b-scale-baseline",
                    "status": "timeout",
                    "threshold_status": "pending_owner_decision",
                    "profile_id": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_id"],
                    "profile_version": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_version"],
                    "page_count": page_count,
                    "timeout_seconds": timeout_seconds,
                    "sampling_interval_seconds": interval,
                    "elapsed_seconds": round(time.monotonic() - started_at, 6),
                    "deterministic_result": "not_available_timeout",
                    **counts,
                    "observer": observer,
                    "memory_observed_bytes": {
                        "baseline": baseline,
                        "peak": peak,
                        "delta": None if baseline is None or peak is None else peak - baseline,
                    },
                    "memory_observer_semantics": "working_set" if observer == "windows" else "rss",
                    "platform": platform.platform(aliased=True),
                    "python": platform.python_version(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {
            "status": "timeout",
            "profile_id": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_id"],
            "profile_version": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_version"],
            "page_count": page_count,
            "window_count": counts["window_count"],
            "occurrence_count": counts["occurrence_count"],
            "timeout_seconds": timeout_seconds,
            "sampling_interval_seconds": interval,
            "elapsed_seconds": round(time.monotonic() - started_at, 6),
            "deterministic_result": "not_available_timeout",
            "observer": observer,
        }
    process.join(30)
    if process.exitcode != 0:
        raise AssertionError("scale child exited unsuccessfully")
    result.update(
        {
            "status": "completed",
            "profile_id": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_id"],
            "profile_version": (PROFILE_V2 if page_count == 100000 else PROFILE_V1)["profile_version"],
            "observer": observer,
            "memory_observed_bytes": {
                "baseline": baseline,
                "peak": peak,
                "delta": None if baseline is None or peak is None else peak - baseline,
            },
            "memory_observer_semantics": "working_set" if observer == "windows" else "rss",
            "sampling_interval_seconds": interval,
            "platform": platform.platform(aliased=True),
            "python": platform.python_version(),
            "deterministic_result": "validated",
        }
    )
    return result


def test_scale_baseline_is_opt_in_and_explicitly_deferred():
    if os.environ.get("KNOWLEDGENEXUS_RUN_SCALE") != "1":
        pytest.skip("opt-in 10k/100k child-process scale baseline")


def test_scale_timeout_artifact_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGENEXUS_SCALE_TIMEOUT_SECONDS", "0.1")
    result = _run_child(tmp_path / "timeout", 100)
    assert result["status"] == "timeout"
    assert result["profile_id"] == PROFILE_V1["profile_id"]
    assert result["deterministic_result"] == "not_available_timeout"
    artifact = json.loads(
        (tmp_path / "timeout" / "m7-c5b-scale-timeout.json").read_text(encoding="utf-8")
    )
    assert artifact["sampling_interval_seconds"] == 0.1
    assert "memory_observed_bytes" in artifact


def test_opt_in_scale_baseline(tmp_path):
    if os.environ.get("KNOWLEDGENEXUS_RUN_SCALE") != "1":
        pytest.skip("opt-in 10k/100k child-process scale baseline")
    extended_a = _run_child(tmp_path / "extended-a", 100000)
    if extended_a["status"] == "timeout":
        assert extended_a["deterministic_result"] == "not_available_timeout"
        assert (tmp_path / "extended-a" / "m7-c5b-scale-timeout.json").exists()
        return
    functional = _run_child(tmp_path / "functional", 10000)
    functional_repeat = _run_child(tmp_path / "functional-repeat", 10000)
    extended_b = _run_child(tmp_path / "extended-b", 100000)
    for result in (functional, functional_repeat, extended_a, extended_b):
        assert result["status"] == "completed"
        assert result["max_window_items"] == 50
        assert result["request_count"] == result["window_count"] + 1
        assert result["observer"]
    for key in ("page_count", "window_count", "request_count", "transition_count", "reservation_count", "trace"):
        assert functional[key] == functional_repeat[key]
        assert extended_a[key] == extended_b[key]
    artifact = {
        "kind": "m7-c5b-scale-baseline",
        "commit": os.environ.get("GIT_COMMIT", "unknown"),
        "threshold_status": "pending_owner_decision",
        "functional": functional,
        "functional_repeat": functional_repeat,
        "extended_first": extended_a,
        "extended_repeat": extended_b,
    }
    artifact_path = tmp_path / "m7-c5b-scale-baseline.json"
    artifact_path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["threshold_status"] == "pending_owner_decision"
