from __future__ import annotations

import urllib.parse

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (  # noqa: E501
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    ConfluenceHttpResponseTooLargeError,
    ConfluenceHttpTransport,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchError,
    ConfluencePageFetchPort,
    ConfluencePageTooLargeError,
)

_PAGE_PATH_TEMPLATE = "/rest/api/content/{page_id}"
# Confirmed by approved M6-0: one page GET with body, space, version, ancestors,
# and labels. M6A preserves the raw response; it does not interpret any of these.
_PAGE_EXPAND = "body.storage,space,version,ancestors,metadata.labels"


class ConfluenceDataCenterPageAdapter(ConfluencePageFetchPort):
    """Data Center implementation of the page fetch port; returns exact bytes."""

    def __init__(self, *, transport: ConfluenceHttpTransport) -> None:
        self._transport = transport

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        page_id = require_confluence_page_id(page_id)
        path = _PAGE_PATH_TEMPLATE.format(
            page_id=urllib.parse.quote(page_id, safe="")
        )
        try:
            return self._transport.get_bytes(
                path=path,
                query={"expand": _PAGE_EXPAND},
            )
        except ConfluenceHttpResponseTooLargeError as exc:
            raise ConfluencePageTooLargeError("page response too large") from exc
        except ConfluenceHttpError as exc:
            raise ConfluencePageFetchError("page fetch failed") from exc

    def fetch_page_response_raw(self, *, page_id: str) -> ConfluenceHttpResponse:
        """Return the exact successful response with its observed HTTP status.

        This additive concrete-adapter seam is for generation evidence capture.
        The established ``fetch_page_raw`` port behavior remains unchanged.
        """

        page_id = require_confluence_page_id(page_id)
        path = _PAGE_PATH_TEMPLATE.format(
            page_id=urllib.parse.quote(page_id, safe="")
        )
        try:
            response = self._transport.get_response_bytes(
                path=path,
                query={"expand": _PAGE_EXPAND},
            )
        except ConfluenceHttpResponseTooLargeError as exc:
            raise ConfluencePageTooLargeError("page response too large") from exc
        except ConfluenceHttpError as exc:
            raise ConfluencePageFetchError("page fetch failed") from exc
        if response.status_code != 200:
            raise ConfluencePageFetchError("page fetch failed")
        return response
