from __future__ import annotations

import logging

from knowledgenexus.retrieval.domain.models.retrieve_request import RetrieveRequest
from knowledgenexus.retrieval.domain.models.retrieve_result import (
    Citation,
    RetrieveResult,
    RetrievedChunk,
)
from knowledgenexus.retrieval.domain.ports import (
    QueryEmbedderPort,
    RetrievalChunkPort,
    RetrievalSearchPort,
)

logger = logging.getLogger(__name__)


class RetrieveChunksUseCase:

    def __init__(
        self,
        query_embedder: QueryEmbedderPort,
        search_port: RetrievalSearchPort,
        chunk_port: RetrievalChunkPort,
    ) -> None:
        self._query_embedder = query_embedder
        self._search_port = search_port
        self._chunk_port = chunk_port

    async def execute(self, request: RetrieveRequest) -> RetrieveResult:
        if not request.query or not request.query.strip():
            raise ValueError("Query must not be empty or whitespace-only")

        embedding = await self._query_embedder.embed_query(request.query)

        scored_chunks = await self._search_port.search(
            query_vector=embedding.values,
            top_k=request.top_k,
            filters=request.filters or None,
        )

        if request.score_threshold > 0:
            scored_chunks = [
                sc for sc in scored_chunks if sc.score >= request.score_threshold
            ]

        scored_chunks = await self._chunk_port.hydrate(scored_chunks)

        results = [self._build_retrieved_chunk(sc) for sc in scored_chunks]

        return RetrieveResult(
            query=request.query,
            total=len(results),
            results=results,
        )

    @staticmethod
    def _build_retrieved_chunk(scored_chunk) -> RetrievedChunk:
        chunk = scored_chunk.chunk
        core = chunk.payload.core
        extra = chunk.payload.extra

        citation = Citation(
            chunk_id=chunk.id,
            document_id=core.document_id,
            title=core.title,
            url=core.url,
            source_type=core.source_type.value,
            source_id=core.source_id,
            chunk_index=core.chunk_index,
            total_chunks=core.total_chunks,
            page_id=extra.get("page_id"),
            space_key=extra.get("space_key"),
            repo=extra.get("repo"),
            branch=extra.get("branch"),
            file_path=extra.get("file_path"),
            symbol=extra.get("symbol"),
            line_start=extra.get("line_start"),
            line_end=extra.get("line_end"),
            heading_path=extra.get("heading_path"),
            content_kind=extra.get("content_kind"),
            language=extra.get("language"),
            source_version=extra.get("source_version"),
        )

        return RetrievedChunk(
            content=chunk.content,
            score=scored_chunk.score,
            citation=citation,
        )
