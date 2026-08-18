"""Chunk and ingest one already-fetched Confluence page.

Bridges Foundation chunking (`ProcessConfluencePageSet`, offline — reads
raw pages already captured by the crawl phases) directly into embedding
+ Qdrant/SQLite storage (`IngestChunkingPacket`), with no intermediate
JSON file.

Live crawling is out of scope here: the caller supplies a `run_id` whose
raw pages were already fetched by the existing, human-run
`inventory`/`capture-pages` CLI phases.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetRequest,
    ConfluencePageWorkItem,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMapperPort,
    ConfluenceStorageNormalizerPort,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStorePort,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.indexing.application.use_cases.chunk_storage_service import (
    ChunkStorageService,
)
from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    IngestChunkingPacket,
    IngestionResult,
)
from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort


class IngestConfluencePage:
    """Chunk one already-fetched Confluence page and ingest it."""

    def __init__(
        self,
        *,
        chunking_profile: ChunkingProfile,
        tokenizer: TokenizerPort,
        raw_page_store: ConfluenceRawPageStorePort,
        raw_page_mapper: ConfluenceRawPageMapperPort,
        storage_normalizer: ConfluenceStorageNormalizerPort,
        schema_validator: object,
        embedder: EmbedderPort,
        chunk_storage_service: ChunkStorageService,
    ) -> None:
        self._processor = ProcessConfluencePageSet(
            chunking_profile=chunking_profile,
            tokenizer=tokenizer,
            raw_page_store=raw_page_store,
            raw_page_mapper=raw_page_mapper,
            storage_normalizer=storage_normalizer,
            schema_validator=schema_validator,
        )
        self._ingestor = IngestChunkingPacket(
            embedder=embedder,
            chunk_storage_service=chunk_storage_service,
        )

    async def execute(self, *, run_id: CrawlRunId, page_id: str) -> IngestionResult:
        """Chunk `page_id` (already fetched under `run_id`) and ingest it."""
        request = ConfluencePageSetRequest(
            run_id=run_id,
            generation_id=run_id,
            items=(
                ConfluencePageWorkItem(
                    page_id=page_id,
                    crawled_at=datetime.now(UTC).isoformat(),
                    expected_source_version=None,
                ),
            ),
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        )
        # ProcessConfluencePageSet is synchronous (tokenizer/parsing is
        # CPU-bound, no network I/O) — run off the event loop.
        result = await asyncio.to_thread(self._processor.execute, request=request)
        return await self._ingestor.execute_records(
            list(result.chunks), list(result.documents)
        )
