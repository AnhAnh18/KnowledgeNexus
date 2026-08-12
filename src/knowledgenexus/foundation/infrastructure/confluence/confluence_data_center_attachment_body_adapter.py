from __future__ import annotations

import unicodedata
import urllib.parse

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
    ConfluenceHttpError,
    ConfluenceHttpResponseTooLargeError,
    ConfluenceHttpTransport,
)
from knowledgenexus.foundation.ports.confluence_attachment_body_fetch_port import (
    ConfluenceAttachmentBodyFetchError,
    ConfluenceAttachmentBodyTooLargeError,
)


_DOWNLOAD_PATH = "/download/attachments/{parent_page_id}/{filename}"
_MAX_FILENAME_BYTES = 512


def _require_filename(value: object) -> str:
    """Validate a filename before it becomes a URL path segment."""
    if type(value) is not str:
        raise TypeError("filename is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > _MAX_FILENAME_BYTES
        or "/" in normalized
        or "\\" in normalized
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in normalized)
    ):
        raise ValueError("filename is invalid")
    return normalized


class ConfluenceDataCenterAttachmentBodyAdapter:
    """Fetch attachment bytes through the bounded Confluence HTTP transport."""

    def __init__(self, *, transport: ConfluenceHttpTransport) -> None:
        if not callable(getattr(transport, "get_response_bytes", None)):
            raise TypeError("transport is invalid")
        self._transport = transport

    def fetch_attachment_body(
        self,
        *,
        attachment_id: str,
        parent_page_id: str,
        filename: str,
        source_version: str,
        max_bytes: int,
    ) -> RawHttpObservation:
        try:
            attachment_id = require_confluence_attachment_id(attachment_id)
            parent_page_id = require_confluence_page_id(parent_page_id)
            filename = _require_filename(filename)
            if (
                type(source_version) is not str
                or not source_version.isascii()
                or not source_version.isdecimal()
                or source_version.startswith("0")
            ):
                raise ValueError("source_version is invalid")
        except (TypeError, ValueError) as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ConfluenceAttachmentBodyFetchError()

        path = _DOWNLOAD_PATH.format(
            parent_page_id=urllib.parse.quote(parent_page_id, safe=""),
            filename=urllib.parse.quote(filename, safe=""),
        )
        try:
            response = self._transport.get_response_bytes(
                path=path,
                query={"version": source_version},
            )
        except ConfluenceHttpResponseTooLargeError as exc:
            raise ConfluenceAttachmentBodyTooLargeError() from exc
        except ConfluenceHttpError as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc
        except (OSError, TypeError, ValueError) as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc
        except Exception as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc

        try:
            status_code = response.status_code
            body = response.body
        except Exception as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc
        if type(status_code) is not int or type(body) is not bytes:
            raise ConfluenceAttachmentBodyFetchError()
        if len(body) > max_bytes:
            raise ConfluenceAttachmentBodyTooLargeError()
        try:
            return RawHttpObservation(status_code=status_code, body=body)
        except (TypeError, ValueError) as exc:
            raise ConfluenceAttachmentBodyFetchError() from exc


__all__ = ["ConfluenceDataCenterAttachmentBodyAdapter"]
