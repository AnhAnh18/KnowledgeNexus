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
        parent_page_id="456",
        filename="architecture diagram.pdf",
        source_version="7",
        max_bytes=1024,
    )

    assert result.status_code == 200
    assert result.body == b"pdf"
    assert transport.calls == [
        ("/download/attachments/456/architecture%20diagram.pdf", {"version": "7"})
    ]


def test_rejects_body_over_requested_limit() -> None:
    transport = FakeTransport(ConfluenceHttpResponse(status_code=200, body=b"1234"))

    with pytest.raises(ConfluenceAttachmentBodyTooLargeError):
        ConfluenceDataCenterAttachmentBodyAdapter(
            transport=transport
        ).fetch_attachment_body(
            attachment_id="123",
            parent_page_id="456",
            filename="a.bin",
            source_version="1",
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
            parent_page_id="456",
            filename="a.bin",
            source_version="1",
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
            parent_page_id="456",
            filename="../secret.bin",
            source_version="1",
            max_bytes=3,
        )
    assert "secret" not in str(exc_info.value)

    with pytest.raises(ConfluenceAttachmentBodyFetchError):
        adapter.fetch_attachment_body(
            attachment_id="bad/id",
            parent_page_id="456",
            filename="a.bin",
            source_version="1",
            max_bytes=3,
        )

    with pytest.raises(ConfluenceAttachmentBodyFetchError):
        adapter.fetch_attachment_body(
            attachment_id="123",
            parent_page_id="456",
            filename="a.bin",
            source_version="1",
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
            parent_page_id="456",
            filename="a.bin",
            source_version="1",
            max_bytes=3,
        )
    assert "host-token-123" not in str(exc_info.value)


@pytest.mark.parametrize(
    "parent_page_id,source_version",
    [
        ("bad/page", "1"),
        ("456", "0"),
        ("456", "01"),
        ("456", "latest"),
        ("456", None),
    ],
)
def test_rejects_unbound_parent_or_attachment_version(
    parent_page_id: object,
    source_version: object,
) -> None:
    transport = FakeTransport(ConfluenceHttpResponse(status_code=200, body=b"body"))

    with pytest.raises(ConfluenceAttachmentBodyFetchError):
        ConfluenceDataCenterAttachmentBodyAdapter(
            transport=transport
        ).fetch_attachment_body(
            attachment_id="123",
            parent_page_id=parent_page_id,  # type: ignore[arg-type]
            filename="a.bin",
            source_version=source_version,  # type: ignore[arg-type]
            max_bytes=10,
        )

    assert transport.calls == []
