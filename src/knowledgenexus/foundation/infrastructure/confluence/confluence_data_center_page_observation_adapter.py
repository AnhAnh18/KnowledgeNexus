from __future__ import annotations

import urllib.parse

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
    ConfluenceHttpError,
    ConfluenceHttpResponseTooLargeError,
    ConfluenceHttpTransport,
)
from knowledgenexus.foundation.ports.confluence_page_observation_port import (
    ConfluenceAttachmentMetadataFetchPort,
    ConfluenceObservationFetchError,
    ConfluenceObservationTooLargeError,
    ConfluenceRestrictionFetchPort,
)

_RESTRICTION_PATH = "/rest/api/content/{page_id}/restriction/byOperation/view"
_ATTACHMENT_PATH = "/rest/api/content/{page_id}/child/attachment"


class ConfluenceDataCenterPageObservationAdapter(
    ConfluenceRestrictionFetchPort,
    ConfluenceAttachmentMetadataFetchPort,
):
    """Fetches one page's restrictions and attachment metadata as raw bytes."""

    def __init__(self, *, transport: ConfluenceHttpTransport) -> None:
        self._transport = transport

    def fetch_view_restriction(self, *, page_id: str) -> RawHttpObservation:
        page_id = require_confluence_page_id(page_id)
        path = _RESTRICTION_PATH.format(
            page_id=urllib.parse.quote(page_id, safe="")
        )
        try:
            response = self._transport.get_response_bytes(path=path, query={})
        except ConfluenceHttpResponseTooLargeError as exc:
            raise ConfluenceObservationTooLargeError(
                "restriction response too large"
            ) from exc
        except ConfluenceHttpError as exc:
            raise ConfluenceObservationFetchError(
                "restriction fetch failed"
            ) from exc
        return RawHttpObservation(
            status_code=response.status_code,
            body=response.body,
        )

    def fetch_attachment_metadata(
        self,
        *,
        page_id: str,
        request: AttachmentMetadataRequest,
    ) -> bytes:
        page_id = require_confluence_page_id(page_id)
        if not isinstance(request, AttachmentMetadataRequest):
            raise TypeError("request expects AttachmentMetadataRequest")
        path = _ATTACHMENT_PATH.format(
            page_id=urllib.parse.quote(page_id, safe="")
        )
        try:
            return self._transport.get_bytes(
                path=path,
                query={"start": str(request.start), "limit": str(request.limit)},
            )
        except ConfluenceHttpResponseTooLargeError as exc:
            raise ConfluenceObservationTooLargeError(
                "attachment response too large"
            ) from exc
        except ConfluenceHttpError as exc:
            raise ConfluenceObservationFetchError(
                "attachment fetch failed"
            ) from exc
