"""Fetch a Confluence page live by URL, then chunk + embed + store it.

Composes `fetch_confluence_page_live` (Foundation, live network fetch) with
`IngestConfluencePage` (chunk + embed + Qdrant/SQLite), mirroring exactly
what `scripts/ingest_confluence_page_live.py` does by hand, so the same
pipeline can be triggered from the API.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from knowledgenexus.foundation.application.use_cases.fetch_confluence_page_live import (
    fetch_confluence_page_live,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.rules.confluence_url import parse_confluence_page_id
from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import IngestionResult
from knowledgenexus.indexing.application.use_cases.ingest_confluence_page import (
    IngestConfluencePage,
)


class IngestConfluencePageFromUrl:
    """Fetch one Confluence page live from a URL, then ingest it."""

    def __init__(
        self,
        *,
        base_url: str,
        pat: str,
        raw_root: Path,
        page_ingestor: IngestConfluencePage,
    ) -> None:
        self._base_url = base_url
        self._pat = pat
        self._raw_root = raw_root
        self._page_ingestor = page_ingestor

    async def execute(self, *, url: str) -> IngestionResult:
        page_id = parse_confluence_page_id(url)
        run_id = CrawlRunId(str(uuid4()))
        self._raw_root.mkdir(parents=True, exist_ok=True)

        # Fetching is synchronous/blocking network I/O — keep it off the event loop.
        await asyncio.to_thread(
            fetch_confluence_page_live,
            base_url=self._base_url,
            pat=self._pat,
            run_id=run_id,
            page_id=page_id,
            raw_root=self._raw_root,
        )
        return await self._page_ingestor.execute(run_id=run_id, page_id=page_id)
