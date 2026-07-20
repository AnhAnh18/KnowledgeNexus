from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterRequestError,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageStore,
    ConfluenceRawPageStoreError,
    RawPageArtifact,
)

# Stable, sanitized failure categories. No category embeds a page id, host,
# title, or response body.
CATEGORY_INVALID_PAGE_ID = "invalid_page_id"
CATEGORY_HTTP = "http"
CATEGORY_MALFORMED_JSON = "malformed_json"
CATEGORY_NON_OBJECT_JSON = "non_object_json"
CATEGORY_IDENTITY_MISMATCH = "identity_mismatch"
CATEGORY_STORE = "store"


class RawPageFetchError(Exception):
    """A sanitized, category-tagged one-page raw fetch failure."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class ConfluencePageRawFetcher(Protocol):
    def fetch_page_raw(self, *, page_id: str) -> bytes: ...


@dataclass(frozen=True)
class RawPageFetchResult:
    """Minimal artifact metadata for callers. Never carries raw content."""

    artifact: RawPageArtifact


class FetchRawConfluencePage:
    """Fetch one page, verify minimally, and preserve its exact raw bytes.

    JSON parsing here is only a pre-publication correctness check; the bytes
    persisted by the store are the exact fetched bytes, never a reserialization.
    """

    def __init__(
        self,
        *,
        page_fetcher: ConfluencePageRawFetcher,
        raw_page_store: ConfluenceRawPageStore,
    ) -> None:
        self._page_fetcher = page_fetcher
        self._raw_page_store = raw_page_store

    def execute(self, *, page_id: str) -> RawPageFetchResult:
        try:
            page_id = require_confluence_page_id(page_id)
        except (TypeError, ValueError) as exc:
            raise RawPageFetchError(CATEGORY_INVALID_PAGE_ID) from exc

        try:
            raw_bytes = self._page_fetcher.fetch_page_raw(page_id=page_id)
        except ConfluenceDataCenterRequestError as exc:
            raise RawPageFetchError(CATEGORY_HTTP) from exc

        _require_identity(raw_bytes=raw_bytes, page_id=page_id)

        try:
            artifact = self._raw_page_store.write(
                page_id=page_id,
                raw_bytes=raw_bytes,
            )
        except (ConfluenceRawPageStoreError, OSError, ValueError, TypeError) as exc:
            raise RawPageFetchError(CATEGORY_STORE) from exc

        return RawPageFetchResult(artifact=artifact)


def _require_identity(*, raw_bytes: bytes, page_id: str) -> None:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawPageFetchError(CATEGORY_MALFORMED_JSON) from exc
    if not isinstance(payload, Mapping):
        raise RawPageFetchError(CATEGORY_NON_OBJECT_JSON)
    observed_id = payload.get("id")
    if isinstance(observed_id, bool) or not isinstance(observed_id, (str, int)):
        raise RawPageFetchError(CATEGORY_IDENTITY_MISMATCH)
    if str(observed_id) != page_id:
        raise RawPageFetchError(CATEGORY_IDENTITY_MISMATCH)
