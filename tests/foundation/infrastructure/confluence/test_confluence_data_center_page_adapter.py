from __future__ import annotations

from collections.abc import Mapping

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageAdapter,
    ConfluenceDataCenterRequestError,
    ConfluenceHttpError,
)

PAGE_ID = "1000"
EXPECTED_PATH = "/rest/api/content/1000"
EXPECTED_EXPAND = "body.storage,space,version,ancestors,metadata.labels"


class RecordingByteTransport:
    def __init__(self, body: bytes = b'{"id":"1000"}') -> None:
        self.body = body
        self.get_bytes_calls: list[dict[str, object]] = []
        self.get_json_calls = 0

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.get_bytes_calls.append({"path": path, "query": dict(query)})
        return self.body

    def get_json(self, *, path: str, query: Mapping[str, str]) -> Mapping[str, object]:
        self.get_json_calls += 1
        raise AssertionError("page fetch must use get_bytes, not get_json")


def test_fetch_issues_exactly_one_page_get_with_confirmed_expand() -> None:
    transport = RecordingByteTransport()
    adapter = ConfluenceDataCenterPageAdapter(transport=transport)

    raw = adapter.fetch_page_raw(page_id=PAGE_ID)

    assert raw == b'{"id":"1000"}'
    assert transport.get_bytes_calls == [
        {"path": EXPECTED_PATH, "query": {"expand": EXPECTED_EXPAND}}
    ]
    assert transport.get_json_calls == 0


def test_fetch_returns_bytes_verbatim() -> None:
    body = '{"id":"1000","body":{"storage":{"value":"<p>x  y</p>\\n"}}}  '.encode()
    adapter = ConfluenceDataCenterPageAdapter(transport=RecordingByteTransport(body))

    assert adapter.fetch_page_raw(page_id=PAGE_ID) == body


def test_no_restriction_attachment_or_inventory_path_is_called() -> None:
    transport = RecordingByteTransport()
    ConfluenceDataCenterPageAdapter(transport=transport).fetch_page_raw(
        page_id=PAGE_ID
    )

    path = transport.get_bytes_calls[0]["path"]
    assert "restriction" not in path
    assert "attachment" not in path
    assert "search" not in path
    assert "child" not in path


def test_http_failure_is_wrapped_and_sanitized() -> None:
    class Failing:
        def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
            raise ConfluenceHttpError("Confluence GET returned HTTP status 404")

    adapter = ConfluenceDataCenterPageAdapter(transport=Failing())

    with pytest.raises(ConfluenceDataCenterRequestError) as exc_info:
        adapter.fetch_page_raw(page_id=PAGE_ID)

    message = str(exc_info.value)
    assert message == "page fetch failed"
    assert PAGE_ID not in message
    assert "404" not in message


@pytest.mark.parametrize(
    "page_id", ["../secret", "1000/child", "a1", "", "1 0", "1.0"]
)
def test_unsafe_page_id_rejected_before_any_request(page_id: str) -> None:
    transport = RecordingByteTransport()
    adapter = ConfluenceDataCenterPageAdapter(transport=transport)

    with pytest.raises(ValueError, match="ASCII decimal digits"):
        adapter.fetch_page_raw(page_id=page_id)

    assert transport.get_bytes_calls == []
