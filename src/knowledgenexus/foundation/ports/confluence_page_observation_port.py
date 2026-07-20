from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
    RawHttpObservation,
)


class ConfluenceObservationFetchError(Exception):
    """A page-adjacent observation could not be fetched safely."""


class ConfluenceObservationTooLargeError(ConfluenceObservationFetchError):
    """An observation response exceeded the configured byte limit."""


class ConfluenceRestrictionFetchPort(Protocol):
    def fetch_view_restriction(self, *, page_id: str) -> RawHttpObservation: ...


class ConfluenceAttachmentMetadataFetchPort(Protocol):
    def fetch_attachment_metadata(
        self,
        *,
        page_id: str,
        request: AttachmentMetadataRequest,
    ) -> bytes: ...
