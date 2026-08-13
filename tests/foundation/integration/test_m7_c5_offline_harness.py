"""Small integrated M7-C acceptance slice using the real SQLite ports."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_workspace import (
    DB_NAME,
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


class ScriptedDurableTransport:
    """A deterministic B3-facing script; no endpoint or HTTP is involved."""

    def __init__(self, activation) -> None:
        self._activation = activation
        self.requests: list[tuple[str, int | None]] = []

    def fetch_root(self, root_page_id: str) -> ConfluencePageMetadata:
        self._reserve()
        self.requests.append(("root", None))
        return ConfluencePageMetadata(root_page_id, "Root", "SPACE")

    def fetch_window(self, start: int) -> ConfluenceInventoryWindow:
        self._reserve()
        self.requests.append(("window", start))
        if start == 0:
            item = ConfluencePageMetadata("1001", "Child 1", "SPACE", "1000", ("1000",), ("Root",))
            return ConfluenceInventoryWindow((item,), 0, 50, 1, 3)
        item = ConfluencePageMetadata("1002", "Child 2", "SPACE", "1000", ("1000",), ("Root",))
        item2 = ConfluencePageMetadata("1003", "Child 3", "SPACE", "1000", ("1000",), ("Root",))
        return ConfluenceInventoryWindow((item, item2), 1, 50, 2, 3)

    def _reserve(self) -> None:
        result = self._activation.reserve_outbound_attempt()
        assert getattr(result, "reservation_sequence", None) is not None


class ScriptedWindowPort:
    def __init__(self, transport: ScriptedDurableTransport) -> None:
        self._transport = transport

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str):
        assert space_key == "SPACE"
        return self._transport.fetch_root(root_page_id)

    def fetch_descendants_window(self, *, space_key: str, root_page_id: str, start: int, page_size: int):
        assert (space_key, root_page_id, page_size) == ("SPACE", "1000", 50)
        return self._transport.fetch_window(start)


def _request(workspace: Path, request_type=StartNewRunRequest):
    config = ConfluenceSourceConfig(
        "synthetic", "SPACE", (ConfluenceIncludeRoot("1000"),), page_size=50
    )
    return request_type(workspace, "https://example.invalid/confluence", config, PROFILE)


def test_real_sqlite_ports_and_scripted_transport_resume_equivalence(tmp_path: Path) -> None:
    workspace = tmp_path
    run_port = SqliteConfluenceCheckpointRunPort()
    transports: list[ScriptedDurableTransport] = []

    def transport_factory(activation):
        transport = ScriptedDurableTransport(activation)
        transports.append(transport)
        return transport

    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=run_port,
        inventory_transport_factory=transport_factory,
        inventory_window_port_factory=ScriptedWindowPort,
    )

    result = use_case.execute(request=_request(workspace))
    assert result.status == "completed", result.operation_failure
    assert [item[0:2] for item in transports[0].requests] == [
        ("root", None),
        ("window", 0),
        ("window", 1),
    ]

    with sqlite3.connect(workspace / DB_NAME) as connection:
        assert connection.execute("SELECT count(*) FROM request_budget_reservations").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM checkpoint_transitions").fetchone() == (4,)
        assert connection.execute("SELECT count(*) FROM inventory_occurrences").fetchone() == (3,)
        assert connection.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions"
        ).fetchall() == [("completed", "completed", "completed")]

    resumed = use_case.execute(request=_request(workspace, ResumeUniqueIncompleteRunRequest))
    assert resumed.status == "inventory_complete"
    assert len(transports) == 1
