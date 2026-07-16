from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageMetadataMapper,
    ConfluenceDataCenterPayloadError,
    ParsedConfluenceSearchPage,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "foundation"
    / "confluence_data_center"
)
ROOT_PAGE_ID = "SELECTED_PAGE"
SPACE_KEY = "SPACE"
_ALLOWED_FIXTURE_KEYS = frozenset(
    {
        "_links",
        "ancestors",
        "content",
        "id",
        "key",
        "labels",
        "limit",
        "metadata",
        "name",
        "next",
        "number",
        "results",
        "self",
        "size",
        "space",
        "start",
        "status",
        "title",
        "totalSize",
        "type",
        "version",
        "when",
    }
)
_ALLOWED_FIXTURE_STRINGS = frozenset(
    {
        "/fixture-labels",
        "/must-not-control-terminal-state",
        "2000-01-01T00:00:00.000+00:00",
        "2000-01-02T00:00:00.000+00:00",
        "2000-01-03T00:00:00.000+00:00",
        "2000-01-04T00:00:00.000+00:00",
        "DIRECT_CHILD",
        "Fixture Direct Child",
        "Fixture Global Page",
        "Fixture Nested Child",
        "Fixture Root Page",
        "Fixture Terminal Child",
        "GLOBAL_PAGE",
        "NESTED_CHILD",
        "SELECTED_PAGE",
        "SPACE",
        "TERMINAL_CHILD",
        "current",
        "page",
    }
)
_ALLOWED_FIXTURE_INTEGERS = frozenset({0, 1, 2, 3, 8, 15, 200})


def test_map_root_supports_captured_missing_space_and_labels_shape() -> None:
    metadata = _map_root(_load_fixture("root_page_response.json"))

    assert metadata.page_id == ROOT_PAGE_ID
    assert metadata.title == "Fixture Root Page"
    assert metadata.space_key == SPACE_KEY
    assert metadata.parent_page_id is None
    assert metadata.ancestor_page_ids == ()
    assert metadata.ancestor_titles == ()
    assert metadata.updated_at == "2000-01-01T00:00:00.000+00:00"
    assert metadata.source_version == "15"
    assert metadata.labels == ()
    assert metadata.attachment_count is None


def test_map_root_accepts_matching_observed_space() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["space"] = {"key": SPACE_KEY}

    assert _map_root(payload).space_key == SPACE_KEY


def test_map_root_rejects_wrong_observed_space() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["space"] = {"key": "OUTSIDE"}

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"root response\.space\.key",
    ):
        _map_root(payload)


def test_map_root_missing_labels_normalizes_to_empty_tuple() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["metadata"] = {}

    assert _map_root(payload).labels == ()


def test_map_root_present_labels_use_domain_normalization() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["metadata"] = {
        "labels": {
            "results": [
                {"name": "z-label"},
                {"name": "a-label"},
                {"name": "z-label"},
            ]
        }
    }

    assert _map_root(payload).labels == ("a-label", "z-label")


def test_map_root_ignores_raw_ancestors_above_selected_root() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["ancestors"] = [{"id": "GLOBAL_PAGE", "title": "Outside"}]

    metadata = _map_root(payload)

    assert metadata.ancestor_page_ids == ()
    assert metadata.ancestor_titles == ()
    assert metadata.parent_page_id is None


def test_map_root_rejects_wrong_root_id() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["id"] = "OTHER_ROOT"

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"root response\.id",
    ):
        _map_root(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (("type", "blogpost"), ("status", "draft")),
)
def test_map_root_rejects_non_page_or_non_current(
    field: str,
    value: str,
) -> None:
    payload = _load_fixture("root_page_response.json")
    payload[field] = value

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=rf"root response\.{field}",
    ):
        _map_root(payload)


def test_map_search_result_normalizes_direct_child_path() -> None:
    result = _search_results()[0]

    metadata = _map_search_result(result)

    assert metadata.page_id == "DIRECT_CHILD"
    assert metadata.ancestor_page_ids == (ROOT_PAGE_ID,)
    assert metadata.ancestor_titles == ("Fixture Root Page",)
    assert metadata.parent_page_id == ROOT_PAGE_ID
    assert metadata.space_key == SPACE_KEY
    assert metadata.source_version == "3"
    assert metadata.labels == ()
    assert metadata.attachment_count is None


def test_map_search_result_normalizes_nested_child_path_and_alignment() -> None:
    result = _search_results()[1]

    metadata = _map_search_result(result)

    assert metadata.ancestor_page_ids == (ROOT_PAGE_ID, "DIRECT_CHILD")
    assert metadata.ancestor_titles == (
        "Fixture Root Page",
        "Fixture Direct Child",
    )
    assert metadata.parent_page_id == "DIRECT_CHILD"
    assert "GLOBAL_PAGE" not in metadata.ancestor_page_ids


@pytest.mark.parametrize("root_count", (0, 2))
def test_map_search_result_requires_selected_root_exactly_once(
    root_count: int,
) -> None:
    result = _search_results()[0]
    content = _content(result)
    ancestors = [{"id": "GLOBAL_PAGE", "title": "Fixture Global Page"}]
    ancestors.extend(
        {"id": ROOT_PAGE_ID, "title": "Fixture Root Page"}
        for _ in range(root_count)
    )
    content["ancestors"] = ancestors

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match="selected root exactly once",
    ):
        _map_search_result(result)


def test_map_search_result_rejects_page_outside_expected_space() -> None:
    result = _search_results()[0]
    _content(result)["space"] = {"key": "OUTSIDE"}

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"search result\.content\.space\.key",
    ):
        _map_search_result(result)


@pytest.mark.parametrize(
    ("field", "value"),
    (("type", "blogpost"), ("status", "draft")),
)
def test_map_search_result_rejects_type_or_status_mismatch(
    field: str,
    value: str,
) -> None:
    result = _search_results()[0]
    _content(result)[field] = value

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=rf"search result\.content\.{field}",
    ):
        _map_search_result(result)


def test_map_search_result_rejects_root_as_descendant() -> None:
    result = _search_results()[0]
    _content(result)["id"] = ROOT_PAGE_ID

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match="not the selected root",
    ):
        _map_search_result(result)


def test_map_search_result_rejects_self_in_retained_ancestors() -> None:
    result = _search_results()[0]
    content = _content(result)
    content["ancestors"].append(
        {"id": content["id"], "title": "Fixture Direct Child"}
    )

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match="descendant page ID",
    ):
        _map_search_result(result)


def test_map_search_result_rejects_duplicate_retained_ancestor() -> None:
    result = _search_results()[1]
    _content(result)["ancestors"].append(
        {"id": "DIRECT_CHILD", "title": "Fixture Direct Child"}
    )

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match="duplicate page IDs",
    ):
        _map_search_result(result)


def test_map_search_result_maps_and_normalizes_labels() -> None:
    result = _search_results()[0]
    _content(result)["metadata"] = {
        "labels": _search_labels("z-label", "a-label", "z-label")
    }

    assert _map_search_result(result).labels == ("a-label", "z-label")


def test_map_search_result_rejects_inconsistent_label_envelope() -> None:
    result = _search_results()[0]
    labels = _content(result)["metadata"]["labels"]
    labels["size"] = 1

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"metadata\.labels\.size",
    ):
        _map_search_result(result)


def test_map_search_result_rejects_subsequent_label_window() -> None:
    result = _search_results()[0]
    labels = _content(result)["metadata"]["labels"]
    labels["_links"]["next"] = "/next-label-window"

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match="subsequent label window",
    ):
        _map_search_result(result)


@pytest.mark.parametrize("mapper_kind", ("root", "search"))
def test_bool_version_is_rejected(mapper_kind: str) -> None:
    if mapper_kind == "root":
        payload = _load_fixture("root_page_response.json")
        payload["version"]["number"] = True
        call = lambda: _map_root(payload)
    else:
        result = _search_results()[0]
        _content(result)["version"]["number"] = True
        call = lambda: _map_search_result(result)

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"version\.number must be an integer",
    ):
        call()


def test_actual_integer_version_is_converted_without_extra_value_policy() -> None:
    payload = _load_fixture("root_page_response.json")
    payload["version"]["number"] = 0

    assert _map_root(payload).source_version == "0"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda content: content.pop("title"), r"content\.title"),
        (lambda content: content.__setitem__("ancestors", {}), r"content\.ancestors"),
        (lambda content: content.__setitem__("version", []), r"content\.version"),
        (
            lambda content: content.__setitem__("metadata", {}),
            r"content\.metadata\.labels",
        ),
    ),
)
def test_map_search_result_rejects_missing_or_malformed_nested_fields(
    mutation: Any,
    expected_path: str,
) -> None:
    result = _search_results()[0]
    mutation(_content(result))

    with pytest.raises(ConfluenceDataCenterPayloadError, match=expected_path):
        _map_search_result(result)


def test_mapper_exceptions_do_not_disclose_raw_or_sensitive_values() -> None:
    result = _search_results()[0]
    content = _content(result)
    sensitive_values = (
        "Sensitive page title",
        "https://private.example.invalid",
        "Bearer private-token",
    )
    content["title"] = sensitive_values[0]
    content["space"] = {"key": sensitive_values[1]}
    content["body"] = sensitive_values[2]

    with pytest.raises(ConfluenceDataCenterPayloadError) as exc_info:
        _map_search_result(result)

    message = str(exc_info.value)
    assert "search result.content.space.key" in message
    assert all(value not in message for value in sensitive_values)


def test_parse_search_page_maps_valid_non_terminal_page() -> None:
    parsed = _parse_search_page(_load_fixture("search_page_start_0.json"))

    assert isinstance(parsed, ParsedConfluenceSearchPage)
    assert parsed.start == 0
    assert parsed.limit == 2
    assert parsed.size == 2
    assert parsed.total_size == 3
    assert parsed.is_terminal is False
    assert tuple(item.page_id for item in parsed.items) == (
        "DIRECT_CHILD",
        "NESTED_CHILD",
    )
    with pytest.raises(AttributeError):
        parsed.start = 1  # type: ignore[misc]


def test_parse_search_page_uses_numbers_not_next_link_for_terminal_state() -> None:
    payload = _load_fixture("search_page_terminal.json")

    parsed = _parse_search_page(payload, expected_start=2)

    assert payload["_links"]["next"]
    assert parsed.is_terminal is True
    assert tuple(item.page_id for item in parsed.items) == ("TERMINAL_CHILD",)


def test_parse_search_page_accepts_confirmed_non_negative_zero_envelope() -> None:
    payload = {
        "results": [],
        "start": 0,
        "limit": 0,
        "size": 0,
        "totalSize": 0,
    }

    parsed = ConfluenceDataCenterPageMetadataMapper.parse_search_page(
        payload=payload,
        expected_start=0,
        expected_limit=0,
        selected_root_page_id=ROOT_PAGE_ID,
        expected_space_key=SPACE_KEY,
    )

    assert parsed.is_terminal is True
    assert parsed.items == ()


def test_parse_search_page_rejects_size_different_from_results_length() -> None:
    payload = _load_fixture("search_page_start_0.json")
    payload["size"] = 1

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"\.size"):
        _parse_search_page(payload)


def test_parse_search_page_rejects_unexpected_start() -> None:
    payload = _load_fixture("search_page_start_0.json")

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"\.start"):
        _parse_search_page(payload, expected_start=2)


def test_parse_search_page_rejects_zero_size_non_terminal_window() -> None:
    payload = _load_fixture("search_page_start_0.json")
    payload["results"] = []
    payload["size"] = 0

    with pytest.raises(ConfluenceDataCenterPayloadError, match="must advance"):
        _parse_search_page(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("start", True),
        ("limit", False),
        ("size", "2"),
        ("totalSize", 3.0),
    ),
)
def test_parse_search_page_rejects_bool_or_non_integer_pagination_values(
    field: str,
    value: object,
) -> None:
    payload = _load_fixture("search_page_start_0.json")
    payload[field] = value

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=rf"\.{field} must be an integer",
    ):
        _parse_search_page(payload)


def test_parse_search_page_rejects_window_past_total_size() -> None:
    payload = _load_fixture("search_page_start_0.json")
    payload["totalSize"] = 1

    with pytest.raises(ConfluenceDataCenterPayloadError, match=r"\.totalSize"):
        _parse_search_page(payload)


def test_parse_search_page_rejects_result_mapping_failure_with_index() -> None:
    payload = _load_fixture("search_page_start_0.json")
    payload["results"][1] = []

    with pytest.raises(
        ConfluenceDataCenterPayloadError,
        match=r"results\[1\]",
    ):
        _parse_search_page(payload)


def test_committed_fixtures_are_sanitized_and_minimal() -> None:
    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert [path.name for path in fixture_paths] == [
        "root_page_response.json",
        "search_page_start_0.json",
        "search_page_terminal.json",
    ]

    generic_forbidden_markers = (
        "Bearer ",
        "Authorization",
        "Cookie",
        '"body"',
        "<SANITIZED_BODY>",
    )
    for fixture_path in fixture_paths:
        text = fixture_path.read_text(encoding="utf-8")
        fixture = json.loads(text)
        _assert_fixture_tree_is_synthetic(fixture)
        assert not any(marker in text for marker in generic_forbidden_markers)
        assert "http://" not in text
        assert "https://" not in text
        assert re.search(r"[\w.+-]+@[\w.-]+", text) is None


def test_fixture_safety_allowlist_rejects_unknown_sanitized_scalar() -> None:
    with pytest.raises(AssertionError):
        _assert_fixture_tree_is_synthetic({"id": "SANITIZED_PAGE_001"})


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _search_results() -> list[dict[str, Any]]:
    return copy.deepcopy(_load_fixture("search_page_start_0.json")["results"])


def _content(result: dict[str, Any]) -> dict[str, Any]:
    return result["content"]


def _search_labels(*names: str) -> dict[str, Any]:
    return {
        "_links": {"self": "/fixture-labels"},
        "limit": 200,
        "results": [{"name": name} for name in names],
        "size": len(names),
        "start": 0,
    }


def _assert_fixture_tree_is_synthetic(value: Any) -> None:
    if isinstance(value, dict):
        assert set(value).issubset(_ALLOWED_FIXTURE_KEYS)
        for nested_value in value.values():
            _assert_fixture_tree_is_synthetic(nested_value)
        return
    if isinstance(value, list):
        for nested_value in value:
            _assert_fixture_tree_is_synthetic(nested_value)
        return
    if isinstance(value, str):
        assert value in _ALLOWED_FIXTURE_STRINGS
        return
    if type(value) is int:
        assert value in _ALLOWED_FIXTURE_INTEGERS
        return
    raise AssertionError(f"fixture contains unsupported scalar type: {type(value)}")


def _map_root(payload: dict[str, Any]):
    return ConfluenceDataCenterPageMetadataMapper.map_root(
        payload=payload,
        expected_root_page_id=ROOT_PAGE_ID,
        expected_space_key=SPACE_KEY,
    )


def _map_search_result(result: dict[str, Any]):
    return ConfluenceDataCenterPageMetadataMapper.map_search_result(
        result=result,
        selected_root_page_id=ROOT_PAGE_ID,
        expected_space_key=SPACE_KEY,
    )


def _parse_search_page(
    payload: dict[str, Any],
    *,
    expected_start: int = 0,
):
    return ConfluenceDataCenterPageMetadataMapper.parse_search_page(
        payload=payload,
        expected_start=expected_start,
        expected_limit=2,
        selected_root_page_id=ROOT_PAGE_ID,
        expected_space_key=SPACE_KEY,
    )
