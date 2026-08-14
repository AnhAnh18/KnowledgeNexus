"""Fetch one already-known Confluence page live and publish its raw envelope.

This is the minimal single-page counterpart to the bulk crawl pipeline
(`confluence_subtree_corpus.py`, phases `inventory`/`capture-pages`): given a
page_id that's already known (e.g. parsed from a URL), fetch it directly via
the Confluence Data Center REST API and store it the same way, so it can be
read back by `ConfluenceRawPageGenerationStore` / `ProcessConfluencePageSet`.
"""

from __future__ import annotations

from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageAdapter,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)


def fetch_confluence_page_live(
    *,
    base_url: str,
    pat: str,
    run_id: CrawlRunId,
    page_id: str,
    raw_root: Path,
) -> None:
    """Fetch `page_id` live from Confluence and publish it into `raw_root`."""
    transport = UrllibConfluenceHttpTransport(base_url=base_url, personal_access_token=pat)
    page_fetcher = ConfluenceDataCenterPageAdapter(transport=transport)
    page_mapper = ConfluenceDataCenterRawPageMapper()
    generation_store = ConfluenceRawPageGenerationStore(raw_root=raw_root)

    response = page_fetcher.fetch_page_response_raw(page_id=page_id)
    source = page_mapper.map_page(raw_bytes=response.body, expected_page_id=page_id)
    envelope = ConfluenceRawPageEnvelope.capture(
        run_id=run_id,
        page_id=page_id,
        source_version=source.source_version,
        http_status=response.status_code,
        body_bytes=response.body,
    )
    generation_store.publish_page(envelope=envelope)
