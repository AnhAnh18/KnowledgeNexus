from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from knowledgenexus.foundation.application.use_cases.build_confluence_inventory import (
    BuildConfluenceInventory,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterInventoryAdapter,
    ConfluenceDataCenterPaginationError,
    ConfluenceDataCenterPayloadError,
    ConfluenceDataCenterRequestError,
    ConfluenceHttpError,
)
from knowledgenexus.foundation.infrastructure.exporters.confluence_inventory_report_writer import (
    ConfluenceInventoryReportWriter,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "foundation"
    / "confluence_data_center"
)
ROOT_PAGE_ID = "1000"
DIRECT_CHILD_ID = "1001"
NESTED_CHILD_ID = "1002"
TERMINAL_CHILD_ID = "1003"
SPACE_KEY = "SPACE"
PAGE_SIZE = 2
ROOT_PATH = f"/rest/api/content/{ROOT_PAGE_ID}"
SEARCH_PATH = "/rest/api/search"
EXPECTED_CQL = f'space="{SPACE_KEY}" and ancestor={ROOT_PAGE_ID} and type=page'
EXPECTED_SEARCH_EXPAND = (
    "content.ancestors,content.space,content.version,content.metadata.labels"
)
_SYNTHETIC_ID_MAP = {
    "GLOBAL_PAGE": "900",
    "SELECTED_PAGE": ROOT_PAGE_ID,
    "DIRECT_CHILD": DIRECT_CHILD_ID,
    "NESTED_CHILD": NESTED_CHILD_ID,
    "TERMINAL_CHILD": TERMINAL_CHILD_ID,
}


class RecordingTransport:
    def __init__(
        self,
        handler: Callable[[str, dict[str, str]], Mapping[str, object]],
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self._handler = handler

    def get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> Mapping[str, object]:
        copied_query = dict(query)
        self.requests.append({"path": path, "query": copied_query})
        return self._handler(path, copied_query)


def test_iteration_is_lazy_and_yields_root_before_descendants() -> None:
    transport = _fixture_transport()
    adapter = _adapter(transport)

    pages = adapter.iter_page_metadata(
        space_key=SPACE_KEY,
        root_page_id=ROOT_PAGE_ID,
        page_size=PAGE_SIZE,
    )
    assert transport.requests == []

    iterator = iter(pages)
    root = next(iterator)
    assert root.page_id == ROOT_PAGE_ID
    assert len(transport.requests) == 1

    direct_child = next(iterator)
    assert direct_child.page_id == DIRECT_CHILD_ID
    assert len(transport.requests) == 2


def test_yields_root_once_then_all_descendants_across_numeric_windows() -> None:
    transport = _fixture_transport()

    pages = list(_iter_pages(_adapter(transport)))

    assert [page.page_id for page in pages] == [
        ROOT_PAGE_ID,
        DIRECT_CHILD_ID,
        NESTED_CHILD_ID,
        TERMINAL_CHILD_ID,
    ]
    assert [page.page_id for page in pages].count(ROOT_PAGE_ID) == 1


def test_issues_exact_root_and_search_request_sequence() -> None:
    transport = _fixture_transport()

    list(_iter_pages(_adapter(transport)))

    assert transport.requests == [
        {
            "path": ROOT_PATH,
            "query": {"expand": "space,version"},
        },
        {
            "path": SEARCH_PATH,
            "query": {
                "cql": EXPECTED_CQL,
                "expand": EXPECTED_SEARCH_EXPAND,
                "limit": "2",
                "start": "0",
            },
        },
        {
            "path": SEARCH_PATH,
            "query": {
                "cql": EXPECTED_CQL,
                "expand": EXPECTED_SEARCH_EXPAND,
                "limit": "2",
                "start": "2",
            },
        },
    ]


def test_root_is_strictly_verified_and_normalized() -> None:
    root = next(iter(_iter_pages(_adapter(_fixture_transport()))))

    assert root.page_id == ROOT_PAGE_ID
    assert root.space_key == SPACE_KEY
    assert root.parent_page_id is None
    assert root.ancestor_page_ids == ()
    assert root.ancestor_titles == ()
    assert root.labels == ()
    assert root.attachment_count is None


@pytest.mark.parametrize(
    "space_value",
    (None, {}, {"key": ""}, {"key": 1}),
)
def test_root_requires_non_empty_raw_space_key(space_value: object) -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        payload = _root_payload()
        if space_value is None:
            payload.pop("space")
        else:
            payload["space"] = space_value
        return payload

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"space"):
        list(_iter_pages(_adapter(RecordingTransport(handler))))


def test_root_wrong_space_fails_before_any_search_request() -> None:
    transport = RecordingTransport(
        lambda path, query: _root_payload(space_key="OUTSIDE")
    )

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"space\.key"):
        list(_iter_pages(_adapter(transport)))

    assert len(transport.requests) == 1


def test_root_wrong_id_fails_through_m5b1_mapper() -> None:
    transport = RecordingTransport(
        lambda path, query: _root_payload(page_id="9999")
    )

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"root response\.id"):
        list(_iter_pages(_adapter(transport)))


def test_scope_query_uses_ancestor_and_only_required_expansions() -> None:
    transport = _fixture_transport()

    list(_iter_pages(_adapter(transport)))

    search_query = transport.requests[1]["query"]
    assert search_query["cql"] == EXPECTED_CQL
    assert "parent" not in search_query["cql"]
    assert search_query["expand"] == EXPECTED_SEARCH_EXPAND
    forbidden_expansions = ("body", "attachment", "restriction", "permission")
    assert all(value not in search_query["expand"] for value in forbidden_expansions)


def test_terminal_state_ignores_bogus_links_next() -> None:
    transport = _fixture_transport()

    list(_iter_pages(_adapter(transport)))

    assert len(transport.requests) == 3
    assert transport.requests[-1]["query"]["start"] == "2"


def test_total_size_may_change_between_windows() -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        if query["start"] == "0":
            payload = _search_payload("search_page_start_0.json")
            payload["totalSize"] = 4
            return payload
        payload = _search_payload("search_page_terminal.json")
        payload["totalSize"] = 3
        return payload

    pages = list(_iter_pages(_adapter(RecordingTransport(handler))))

    assert len(pages) == 4


def test_non_terminal_zero_size_window_fails_through_m5b1_parser() -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        return {
            "results": [],
            "start": 0,
            "limit": PAGE_SIZE,
            "size": 0,
            "totalSize": 1,
        }

    with pytest.raises(ConfluenceDataCenterPayloadError, match="must advance"):
        list(_iter_pages(_adapter(RecordingTransport(handler))))


def test_explicit_search_page_budget_fails_closed_without_truncating() -> None:
    def never_terminal(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        payload = _search_payload("search_page_start_0.json")
        start = int(query["start"])
        payload["start"] = start
        payload["totalSize"] = start + payload["size"] + 1
        return payload

    transport = RecordingTransport(never_terminal)
    adapter = _adapter(transport, max_search_pages=2)

    with pytest.raises(
        ConfluenceDataCenterPaginationError,
        match="max_search_pages",
    ):
        list(_iter_pages(adapter))

    assert len(transport.requests) == 3


def test_page_budget_allows_terminal_response_on_final_permitted_window() -> None:
    transport = _fixture_transport()

    pages = list(_iter_pages(_adapter(transport, max_search_pages=2)))

    assert len(pages) == 4


def test_malformed_later_window_error_propagates() -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        payload = _search_payload("search_page_start_0.json")
        if query["start"] == "2":
            payload["start"] = 999
        return payload

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"\.start"):
        list(_iter_pages(_adapter(RecordingTransport(handler))))


def test_later_http_error_is_operation_scoped_and_not_retried() -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        if path == ROOT_PATH:
            return _root_payload()
        if query["start"] == "0":
            return _search_payload("search_page_start_0.json")
        raise ConfluenceHttpError("Confluence GET returned HTTP status 503")

    transport = RecordingTransport(handler)

    with pytest.raises(ConfluenceDataCenterRequestError) as exc_info:
        list(_iter_pages(_adapter(transport)))

    assert str(exc_info.value) == (
        "search window failed at start 2: "
        "Confluence GET returned HTTP status 503"
    )
    assert len(transport.requests) == 3


def test_root_http_error_is_safe_and_does_not_disclose_identifiers() -> None:
    def handler(path: str, query: dict[str, str]) -> Mapping[str, object]:
        raise ConfluenceHttpError("Confluence GET failed")

    with pytest.raises(ConfluenceDataCenterRequestError) as exc_info:
        list(_iter_pages(_adapter(RecordingTransport(handler))))

    message = str(exc_info.value)
    assert message == "root fetch failed: Confluence GET failed"
    assert ROOT_PAGE_ID not in message
    assert SPACE_KEY not in message


@pytest.mark.parametrize(
    "space_key",
    ('SPACE" or type=page', "SPA CE", "SPACE'", "SPACE\\", ""),
)
def test_rejects_cql_unsafe_space_key_before_http(space_key: str) -> None:
    transport = _fixture_transport()

    with pytest.raises(ValueError, match="unsafe for CQL"):
        _adapter(transport).iter_page_metadata(
            space_key=space_key,
            root_page_id=ROOT_PAGE_ID,
            page_size=PAGE_SIZE,
        )

    assert transport.requests == []


def test_accepts_confirmed_safe_space_key_charset() -> None:
    transport = _fixture_transport()

    _adapter(transport).iter_page_metadata(
        space_key="SPACE-1_A.B",
        root_page_id=ROOT_PAGE_ID,
        page_size=PAGE_SIZE,
    )

    assert transport.requests == []


@pytest.mark.parametrize(
    "root_page_id",
    ("SELECTED_PAGE", "123 or type=page", "１２３", "-1", "", "1.0"),
)
def test_rejects_non_ascii_decimal_root_id_before_http(
    root_page_id: str,
) -> None:
    transport = _fixture_transport()

    with pytest.raises(ValueError, match="ASCII decimal digits"):
        _adapter(transport).iter_page_metadata(
            space_key=SPACE_KEY,
            root_page_id=root_page_id,
            page_size=PAGE_SIZE,
        )

    assert transport.requests == []


@pytest.mark.parametrize("page_size", (0, -1))
def test_rejects_non_positive_page_size(page_size: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _adapter(_fixture_transport()).iter_page_metadata(
            space_key=SPACE_KEY,
            root_page_id=ROOT_PAGE_ID,
            page_size=page_size,
        )


@pytest.mark.parametrize("page_size", (True, 2.0, "2"))
def test_rejects_non_integer_page_size(page_size: object) -> None:
    with pytest.raises(TypeError, match="expects an integer"):
        _adapter(_fixture_transport()).iter_page_metadata(
            space_key=SPACE_KEY,
            root_page_id=ROOT_PAGE_ID,
            page_size=page_size,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("max_search_pages", (0, -1))
def test_rejects_non_positive_search_page_budget(max_search_pages: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _adapter(_fixture_transport(), max_search_pages=max_search_pages)


@pytest.mark.parametrize("max_search_pages", (True, 2.0, "2"))
def test_rejects_non_integer_search_page_budget(max_search_pages: object) -> None:
    with pytest.raises(TypeError, match="expects an integer"):
        ConfluenceDataCenterInventoryAdapter(
            transport=_fixture_transport(),
            max_search_pages=max_search_pages,  # type: ignore[arg-type]
        )


def test_m5a_scope_and_report_integration_remain_unchanged(tmp_path: Path) -> None:
    config = ConfluenceSourceConfig(
        source_id="fixture-source",
        space_key=SPACE_KEY,
        include_roots=(ConfluenceIncludeRoot(page_id=ROOT_PAGE_ID),),
        exclude_subtrees=(
            ConfluenceExcludeSubtree(
                page_id=DIRECT_CHILD_ID,
                reason="fixture exclusion",
            ),
        ),
        page_size=PAGE_SIZE,
    )

    items = BuildConfluenceInventory(
        inventory_port=_adapter(_fixture_transport())
    ).execute(config=config)

    by_id = {item.page_id: item for item in items}
    assert by_id[ROOT_PAGE_ID].scope_status == "included"
    assert by_id[DIRECT_CHILD_ID].scope_status == "excluded_subtree"
    assert by_id[NESTED_CHILD_ID].scope_status == "excluded_subtree"
    assert by_id[TERMINAL_CHILD_ID].scope_status == "included"
    assert ConfluenceInventoryReportWriter.write(
        output_dir=tmp_path,
        items=items,
    ) == 4
    assert (tmp_path / "pages_inventory.jsonl").is_file()
    assert (tmp_path / "inventory_report.csv").is_file()


def _adapter(
    transport: RecordingTransport,
    *,
    max_search_pages: int = 10,
) -> ConfluenceDataCenterInventoryAdapter:
    return ConfluenceDataCenterInventoryAdapter(
        transport=transport,
        max_search_pages=max_search_pages,
    )


def _iter_pages(adapter: ConfluenceDataCenterInventoryAdapter) -> Any:
    return adapter.iter_page_metadata(
        space_key=SPACE_KEY,
        root_page_id=ROOT_PAGE_ID,
        page_size=PAGE_SIZE,
    )


def _fixture_transport() -> RecordingTransport:
    return RecordingTransport(_serve_fixtures)


def _serve_fixtures(
    path: str,
    query: dict[str, str],
) -> Mapping[str, object]:
    if path == ROOT_PATH:
        return _root_payload()
    if path == SEARCH_PATH and query["start"] == "0":
        return _search_payload("search_page_start_0.json")
    if path == SEARCH_PATH and query["start"] == "2":
        return _search_payload("search_page_terminal.json")
    raise AssertionError("unexpected fixture request")


def _root_payload(
    *,
    page_id: str = ROOT_PAGE_ID,
    space_key: str = SPACE_KEY,
) -> dict[str, Any]:
    payload = _load_fixture("root_page_response.json")
    payload["id"] = page_id
    payload["space"] = {"key": space_key}
    return payload


def _search_payload(name: str) -> dict[str, Any]:
    return _replace_fixture_ids(_load_fixture(name))


def _replace_fixture_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_fixture_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_fixture_ids(item) for item in value]
    if isinstance(value, str):
        return _SYNTHETIC_ID_MAP.get(value, value)
    return value


def _load_fixture(name: str) -> dict[str, Any]:
    return copy.deepcopy(
        json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    )
