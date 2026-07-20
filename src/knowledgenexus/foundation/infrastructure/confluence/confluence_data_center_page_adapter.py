from __future__ import annotations

import urllib.parse

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_inventory_adapter import (  # noqa: E501
    ConfluenceDataCenterRequestError,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (  # noqa: E501
    ConfluenceHttpError,
    ConfluenceHttpTransport,
)

_PAGE_PATH_TEMPLATE = "/rest/api/content/{page_id}"
# Confirmed by approved M6-0: one page GET with body, space, version, ancestors,
# and labels. M6A preserves the raw response; it does not interpret any of these.
_PAGE_EXPAND = "body.storage,space,version,ancestors,metadata.labels"


class ConfluenceDataCenterPageAdapter:
    """Fetches one raw Confluence Data Center page response as exact bytes."""

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
        except ConfluenceHttpError as exc:
            raise ConfluenceDataCenterRequestError(
                "page fetch failed"
            ) from exc
