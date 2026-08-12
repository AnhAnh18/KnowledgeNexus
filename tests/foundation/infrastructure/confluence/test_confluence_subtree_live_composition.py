from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    compose_live_subtree,
)
import knowledgenexus.foundation.infrastructure.confluence.confluence_subtree_live_composition as module


def _profile() -> dict[str, object]:
    # Minimal valid retry profile; values mirror the approved production profile.
    return {
        "minimum_request_interval_seconds": 3.0,
        "max_attempts_per_request": 3,
        "max_total_requests_per_run": 100,
        "max_total_retry_sleep_seconds": 30.0,
        "max_raw_bytes_per_run": 34359738368,
        "minimum_free_disk_reserve_bytes": 8589934592,
    }


def test_composes_concrete_inventory_and_page_adapters_without_network(monkeypatch, tmp_path: Path):
    calls: list[str] = []
    raw_kwargs: dict[str, object] = {}

    class Transport:
        pass

    class Inner:
        def __init__(self, **kwargs):
            calls.append("inner")

    class Retry:
        def __init__(self, **kwargs):
            calls.append("retry")

    class Inventory:
        def __init__(self, **kwargs):
            calls.append("inventory")

    class Page:
        def __init__(self, **kwargs):
            calls.append("page")

    monkeypatch.setattr(module, "UrllibConfluenceHttpTransport", Inner)
    monkeypatch.setattr(module, "RetryingConfluenceHttpTransport", Retry)
    monkeypatch.setattr(module, "ConfluenceDataCenterInventoryAdapter", Inventory)
    monkeypatch.setattr(module, "ConfluenceDataCenterPageAdapter", Page)
    monkeypatch.setattr(module, "ConfluenceRetryExecutorProfile", type("Profile", (), {"from_mapping": staticmethod(lambda _: object())}))
    def raw_store(**kwargs):
        calls.append("raw")
        return object()

    def budgeted_store(**kwargs):
        raw_kwargs.update(kwargs)
        calls.append("budget")
        return object()

    monkeypatch.setattr(module, "ConfluenceRawPageGenerationStore", raw_store)
    monkeypatch.setattr(module, "BudgetedConfluenceRawPageStore", budgeted_store)

    composition = compose_live_subtree(
        raw_root=tmp_path / "raw",
        checkpoint_workspace=tmp_path / "checkpoint",
        reliability_profile=_profile(),
        max_search_pages=50,
        base_url="https://example.invalid",
        personal_access_token="secret",
    )

    assert calls == ["inner", "retry", "inventory", "page", "raw"]
    assert composition.__repr__() == "LiveSubtreeComposition()"
    use_case = composition.inventory_use_case(max_search_pages=50)
    assert use_case.__class__.__name__ == "ExecuteDurableConfluenceInventory"
    # The factory must build the approved concrete inventory adapter rather
    # than accepting a callback that can silently bypass production seams.
    use_case._inventory_window_port_factory(composition.transport)
    assert calls[-1] == "inventory"
    class Activation:
        @staticmethod
        def guard_raw_publication():
            from contextlib import nullcontext
            return nullcontext()
    composition.guarded_raw_page_store(activation=Activation())
    assert calls[-1] == "budget"
    assert raw_kwargs["max_total_bytes"] == 34359738368
    assert raw_kwargs["minimum_free_disk_reserve_bytes"] == 8589934592
    assert callable(raw_kwargs["publication_guard"])


def test_credentials_are_environment_only_and_missing_fails(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)
    monkeypatch.delenv("CONFLUENCE_PAT", raising=False)
    with pytest.raises(ValueError, match="credentials"):
        compose_live_subtree(
            raw_root=tmp_path / "raw",
            checkpoint_workspace=tmp_path / "checkpoint",
            reliability_profile=_profile(),
            max_search_pages=1,
        )
