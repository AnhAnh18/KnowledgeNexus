from __future__ import annotations

from collections.abc import Mapping

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterAttachmentBodyAdapter,
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    ConfluenceHttpResponseTooLargeError,
)
from knowledgenexus.foundation.ports.confluence_attachment_body_fetch_port import (
    ConfluenceAttachmentBodyFetchError,
    ConfluenceAttachmentBodyTooLargeError,
)


class FakeTransport:
    def __init__(self, response: ConfluenceHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_response_bytes(
        self, *, path: str, query: Mapping[str, str]
    ) -> ConfluenceHttpResponse:
        self.calls.append((path, dict(query)))
        return self.response


def test_fetches_download_endpoint_and_preserves_response() -> None:
    transport = FakeTransport(ConfluenceHttpResponse(status_code=200, body=b"pdf"))

    result = ConfluenceDataCenterAttachmentBodyAdapter(
        transport=transport
    ).fetch_attachment_body(
        attachment_id="att123",
        filename="architecture diagram.pdf",
        max_bytes=1024,
    )

    assert result.status_code == 200
    assert result.body == b"pdf"
    assert transport.calls == [
        ("/download/attachments/att123/architecture%20diagram.pdf", {})
    ]


def test_rejects_body_over_requested_limit() -> None:
    transport = FakeTransport(ConfluenceHttpResponse(status_code=200, body=b"1234"))

    with pytest.raises(ConfluenceAttachmentBodyTooLargeError):
        ConfluenceDataCenterAttachmentBodyAdapter(
            transport=transport
        ).fetch_attachment_body(
            attachment_id="123",
            filename="a.bin",
            max_bytes=3,
        )


def test_maps_transport_size_failure_to_port_error() -> None:
    class TooLarge(FakeTransport):
        def get_response_bytes(self, **kwargs: object) -> ConfluenceHttpResponse:
            raise ConfluenceHttpResponseTooLargeError("secret")

    with pytest.raises(ConfluenceAttachmentBodyTooLargeError):
        ConfluenceDataCenterAttachmentBodyAdapter(
            transport=TooLarge(ConfluenceHttpResponse(status_code=200, body=b""))
        ).fetch_attachment_body(
            attachment_id="123",
            filename="a.bin",
            max_bytes=3,
        )


def test_maps_transport_failure_and_rejects_unsafe_path_inputs() -> None:
    class Failing(FakeTransport):
        def get_response_bytes(self, **kwargs: object) -> ConfluenceHttpResponse:
            raise ConfluenceHttpError("credential/secret")

    adapter = ConfluenceDataCenterAttachmentBodyAdapter(
        transport=Failing(ConfluenceHttpResponse(status_code=200, body=b""))
    )
    with pytest.raises(ConfluenceAttachmentBodyFetchError) as exc_info:
        adapter.fetch_attachment_body(
            attachment_id="123",
            filename="../secret.bin",
            max_bytes=3,
        )
    assert "secret" not in str(exc_info.value)

    with pytest.raises(ConfluenceAttachmentBodyFetchError):
        adapter.fetch_attachment_body(
            attachment_id="bad/id",
            filename="a.bin",
            max_bytes=3,
        )

    with pytest.raises(ConfluenceAttachmentBodyFetchError):
        adapter.fetch_attachment_body(
            attachment_id="123",
            filename="a.bin",
            max_bytes=0,
        )


def test_maps_transport_error_without_leaking_details() -> None:
    class Failing(FakeTransport):
        def get_response_bytes(self, **kwargs: object) -> ConfluenceHttpResponse:
            raise ConfluenceHttpError("host-token-123")

    with pytest.raises(ConfluenceAttachmentBodyFetchError) as exc_info:
        ConfluenceDataCenterAttachmentBodyAdapter(
            transport=Failing(ConfluenceHttpResponse(status_code=200, body=b""))
        ).fetch_attachment_body(
            attachment_id="123",
            filename="a.bin",
            max_bytes=3,
        )
    assert "host-token-123" not in str(exc_info.value)
