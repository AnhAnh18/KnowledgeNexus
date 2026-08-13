from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopPolicy,
)
from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
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
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_inventory_adapter import (
    ConfluenceDataCenterInventoryAdapter,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    ResumeExplicitRunRequest,
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

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "foundation" / "confluence_data_center"


class ScriptedTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self._root = {
            "id": "1000",
            "status": "current",
            "title": "Fixture Root Page",
            "type": "page",
            "space": {"key": "SPACE"},
            "version": {"number": 15, "when": "2000-01-01T00:00:00.000+00:00"},
        }
        first = json.loads((FIXTURES / "search_page_start_0.json").read_text())
        item = copy.deepcopy(first["results"][0])
        item["content"]["id"] = "1001"
        item["content"]["ancestors"] = [{"id": "1000", "title": "Fixture Root Page"}]
        self._windows = {
            0: {
            "limit": 50,
            "results": [item],
            "size": 1,
            "start": 0,
            "totalSize": 2,
            },
            1: {
                "limit": 50,
                "results": [copy.deepcopy(item)],
                "size": 1,
                "start": 1,
                "totalSize": 2,
            },
        }
        self._windows[1]["results"][0]["content"]["id"] = "1002"

    def get_json(self, *, path: str, query: dict[str, str]) -> dict[str, object]:
        self.requests.append((path, tuple(sorted(query.items()))))
        if path.startswith("/rest/api/content/"):
            return copy.deepcopy(self._root)
        return copy.deepcopy(self._windows[int(query.get("start", "0"))])


class GeneratedWindowPort:
    def __init__(self, total: int = 9999, page_size: int = 50) -> None:
        self.total = total
        self.page_size = page_size
        self.max_window_items = 0
        self.window_calls = 0

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str):
        return ConfluencePageMetadata(root_page_id, "Fixture Root", space_key)

    def fetch_descendants_window(
        self, *, space_key: str, root_page_id: str, start: int, page_size: int
    ) -> ConfluenceInventoryWindow:
        count = min(page_size, self.total - start)
        items = tuple(
            ConfluencePageMetadata(
                str(1001 + start + ordinal),
                f"Page {start + ordinal}",
                space_key,
                root_page_id,
                (root_page_id,),
                ("Fixture Root",),
            )
            for ordinal in range(count)
        )
        self.max_window_items = max(self.max_window_items, len(items))
        self.window_calls += 1
        return ConfluenceInventoryWindow(items, start, page_size, count, self.total)


def _request(workspace: Path, request_type=StartNewRunRequest, run_id=None):
    config = ConfluenceSourceConfig(
        "source", "SPACE", (ConfluenceIncludeRoot("1000"),)
    )
    if request_type is ResumeExplicitRunRequest:
        return request_type(
            workspace,
            run_id,
            "https://fixture.invalid/confluence",
            config,
            PROFILE,
        )
    return request_type(
        workspace,
        "https://fixture.invalid/confluence",
        config,
        PROFILE,
    )


def _execute(workspace: Path, transport: ScriptedTransport):
    adapter = ConfluenceDataCenterInventoryAdapter(
        transport=transport,
        max_search_pages=1000,
    )
    return ExecuteDurableConfluenceInventory(
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        inventory_transport_factory=lambda activation: transport,
        inventory_window_port_factory=lambda value: adapter,
    )


def test_real_sqlite_pause_then_resume_closes_sessions_and_is_deterministic(tmp_path) -> None:
    transport = ScriptedTransport()
    use_case = _execute(tmp_path, transport)
    paused = use_case.execute(
        request=_request(tmp_path),
        controlled_stop_policy=ControlledStopPolicy(1),
    )

    assert paused.status == "paused"
    run_id = paused.snapshot.run_id
    assert transport.requests == [
        ("/rest/api/content/1000", (("expand", "space,version"),)),
        ("/rest/api/search", tuple(sorted({
            "cql": 'space="SPACE" and ancestor=1000 and type=page',
            "expand": "content.ancestors,content.space,content.version,content.metadata.labels",
            "limit": "50",
            "start": "0",
        }.items()))),
    ]

    resumed = use_case.execute(
        request=_request(tmp_path, ResumeExplicitRunRequest, run_id),
    )
    assert resumed.status == "completed"

    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as connection:
        sessions = connection.execute(
            "SELECT status,outcome_status,outcome_reason FROM crawl_sessions "
            "ORDER BY started_at,session_id"
        ).fetchall()
    assert sessions == [
        ("paused", "paused", "controlled_checkpoint_stop"),
        ("completed", "completed", "completed"),
    ]


def test_functional_scale_corpus_is_window_bounded_at_10000_pages(tmp_path) -> None:
    generated = GeneratedWindowPort()
    use_case = ExecuteDurableConfluenceInventory(
        checkpoint_run_port=SqliteConfluenceCheckpointRunPort(),
        inventory_transport_factory=lambda activation: activation,
        inventory_window_port_factory=lambda value: generated,
    )

    result = use_case.execute(request=_request(tmp_path))

    assert result.status == "completed"
    assert generated.window_calls == 200
    assert generated.max_window_items == 50
    with sqlite3.connect(tmp_path / "crawl_state.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_occurrences"
        ).fetchone() == (9999,)
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_windows"
        ).fetchone() == (200,)
