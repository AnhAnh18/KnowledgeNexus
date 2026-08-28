"""Serve unchanged pages from a prior generation's raw evidence.

A live sync re-crawls the whole subtree because the capture contract binds a run
to its full inventory. But a page whose ``source_version`` did not move has
byte-identical content in the accepted baseline, so its raw response never needs
to be fetched again. This decorator returns the baseline body for those pages
and delegates every other page to the live fetcher.

It changes nothing downstream: ``FetchAndStoreConfluenceRawPageGeneration``
re-derives the version from whatever bytes ``fetch_page_raw`` returns and stores
them under the new generation exactly as if they had come off the network, so
the checkpoint, acknowledge, and export invariants are untouched.
"""
from __future__ import annotations

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchPort,
)


class BaselineAwarePageFetcher(ConfluencePageFetchPort):
    """Reuse baseline raw bodies for unchanged pages; fetch the rest live.

    ``baseline_bodies`` maps a page id to the raw response bytes captured for it
    in the accepted baseline. A page appears here only when the caller has
    already confirmed its version is unchanged, so a hit is always safe to serve
    without a network round-trip. A miss delegates to ``inner`` — which also
    means a pruned or version-mismatched baseline degrades to a live fetch
    rather than an error.
    """

    def __init__(
        self, *, inner: ConfluencePageFetchPort, baseline_bodies: dict[str, bytes]
    ) -> None:
        if not callable(getattr(inner, "fetch_page_raw", None)):
            raise TypeError("inner fetcher is invalid")
        if type(baseline_bodies) is not dict:
            raise TypeError("baseline_bodies is invalid")
        validated: dict[str, bytes] = {}
        for page_id, body in baseline_bodies.items():
            if type(body) is not bytes or not body:
                raise ValueError("baseline body is invalid")
            validated[require_confluence_page_id(page_id)] = body
        self._inner = inner
        self._baseline_bodies = validated
        self._reused = 0
        self._fetched = 0

    @property
    def reused_pages(self) -> int:
        return self._reused

    @property
    def fetched_pages(self) -> int:
        return self._fetched

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        page_id = require_confluence_page_id(page_id)
        body = self._baseline_bodies.get(page_id)
        if body is not None:
            self._reused += 1
            return body
        self._fetched += 1
        return self._inner.fetch_page_raw(page_id=page_id)
