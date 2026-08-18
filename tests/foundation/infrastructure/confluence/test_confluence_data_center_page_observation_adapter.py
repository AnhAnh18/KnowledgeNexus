from __future__ import annotations

from collections.abc import Mapping

import pytest

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageObservationAdapter,
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    ConfluenceHttpResponseTooLargeError,
)
from knowledgenexus.foundation.ports.confluence_page_observation_port import (
    ConfluenceObservationFetchError,
    ConfluenceObservationTooLargeError,
)


class FakeTransport:
    def __init__(self, response: ConfluenceHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def get_response_bytes(
        self, *, path: str, query: Mapping[str, str]
    ) -> ConfluenceHttpResponse:
        self.calls.append(("status", path, dict(query)))
        return self.response

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.calls.append(("bytes", path, dict(query)))
        return self.response.body

    def get_json(self, *, path: str, query: Mapping[str, str]) -> Mapping[str, object]:
        raise AssertionError("M6B adapter must not use get_json")


def test_restriction_uses_exact_endpoint_and_preserves_status_and_body() -> None:
    raw = b"<html>synthetic unavailable</html>"
    transport = FakeTransport(ConfluenceHttpResponse(status_code=404, body=raw))

    response = ConfluenceDataCenterPageObservationAdapter(
        transport=transport
    ).fetch_view_restriction(page_id="1000")

    assert response.status_code == 404
    assert response.body == raw
    assert transport.calls == [
        (
            "status",
            "/rest/api/content/1000/restriction/byOperation/view",
            {},
        )
    ]


@pytest.mark.parametrize("status", [200, 401, 403, 404])
def test_restriction_accepts_only_defined_observation_statuses(status: int) -> None:
    adapter = ConfluenceDataCenterPageObservationAdapter(
        transport=FakeTransport(ConfluenceHttpResponse(status_code=status, body=b""))
    )
    assert adapter.fetch_view_restriction(page_id="1000").status_code == status


def test_restriction_returns_unexpected_status_so_caller_can_preserve_then_fail() -> None:
    adapter = ConfluenceDataCenterPageObservationAdapter(
        transport=FakeTransport(ConfluenceHttpResponse(status_code=500, body=b"secret"))
    )
    response = adapter.fetch_view_restriction(page_id="1000")
    assert response.status_code == 500
    assert response.body == b"secret"


def test_attachment_uses_exact_endpoint_and_actual_window() -> None:
    raw = b'{"results":[]}'
    transport = FakeTransport(ConfluenceHttpResponse(status_code=200, body=raw))

    result = ConfluenceDataCenterPageObservationAdapter(
        transport=transport
    ).fetch_attachment_metadata(
        page_id="1000",
        request=AttachmentMetadataRequest(start=7, limit=3),
    )

    assert result == raw
    assert transport.calls == [
        (
            "bytes",
            "/rest/api/content/1000/child/attachment",
            # `expand` is not optional: Data Center omits version and metadata
            # without it, and an attachment with no version is rejected
            # downstream as an invalid observation.
            {"start": "7", "limit": "3", "expand": "version,metadata"},
        )
    ]


@pytest.mark.parametrize("method", ["restriction", "attachment"])
def test_transport_failures_map_to_sanitized_port_errors(method: str) -> None:
    class Failing(FakeTransport):
        def get_response_bytes(self, **kwargs: object) -> ConfluenceHttpResponse:
            raise ConfluenceHttpError("host secret id principal")

        def get_bytes(self, **kwargs: object) -> bytes:
            raise ConfluenceHttpError("host secret id filename")

    adapter = ConfluenceDataCenterPageObservationAdapter(
        transport=Failing(ConfluenceHttpResponse(status_code=200, body=b""))
    )
    with pytest.raises(ConfluenceObservationFetchError) as exc_info:
        if method == "restriction":
            adapter.fetch_view_restriction(page_id="1000")
        else:
            adapter.fetch_attachment_metadata(
                page_id="1000",
                request=AttachmentMetadataRequest(start=0, limit=2),
            )
    assert "secret" not in str(exc_info.value)
    assert "1000" not in str(exc_info.value)


def test_response_limit_has_distinct_port_error() -> None:
    class TooLarge(FakeTransport):
        def get_response_bytes(self, **kwargs: object) -> ConfluenceHttpResponse:
            raise ConfluenceHttpResponseTooLargeError("too large")

    adapter = ConfluenceDataCenterPageObservationAdapter(
        transport=TooLarge(ConfluenceHttpResponse(status_code=200, body=b""))
    )
    with pytest.raises(ConfluenceObservationTooLargeError):
        adapter.fetch_view_restriction(page_id="1000")


def test_attachment_listing_expands_version_and_metadata():
    """Data Center omits both unless asked, and the body materializer needs them.

    Without `expand`, `version` never arrives, so `source_version` is None and
    every attachment is rejected as an invalid observation -- which is why no
    draw.io diagram could be downloaded. `extensions.fileSize` comes back
    regardless, which is what made the gap look like a validation bug.
    """
    class _Transport:
        def __init__(self):
            self.query = None

        def get_bytes(self, *, path, query):
            self.query = query
            return b"{}"

    transport = _Transport()
    adapter = ConfluenceDataCenterPageObservationAdapter(transport=transport)

    adapter.fetch_attachment_metadata(
        page_id="2894336117", request=AttachmentMetadataRequest(start=0, limit=50)
    )

    assert transport.query["expand"] == "version,metadata"
    assert transport.query["start"] == "0"
    assert transport.query["limit"] == "50"
