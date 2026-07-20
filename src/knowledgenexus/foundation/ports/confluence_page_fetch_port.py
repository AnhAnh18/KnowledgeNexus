from __future__ import annotations

from typing import Protocol


class ConfluencePageFetchError(Exception):
    """A page could not be fetched. Sanitized: carries no host, id, or body."""


class ConfluencePageTooLargeError(ConfluencePageFetchError):
    """The page response exceeded the configured size limit."""


class ConfluencePageFetchPort(Protocol):
    """Fetches one raw Confluence page response as exact bytes."""

    def fetch_page_raw(self, *, page_id: str) -> bytes: ...
