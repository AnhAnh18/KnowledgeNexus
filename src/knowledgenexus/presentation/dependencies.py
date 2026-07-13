from __future__ import annotations

from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase


def get_retrieve_chunks_use_case() -> RetrieveChunksUseCase:
    from knowledgenexus.retrieval.infrastructure.query_adapters import (
        IndexingChunkAdapter,
        IndexingEmbedderAdapter,
        IndexingSearchAdapter,
    )
    from knowledgenexus.shared.di import get_container

    container = get_container()

    embedder_adapter = IndexingEmbedderAdapter(container.get_embedder())
    search_adapter = IndexingSearchAdapter(container.vector_store)
    chunk_adapter = IndexingChunkAdapter(container.chunk_repo)

    return RetrieveChunksUseCase(
        query_embedder=embedder_adapter,
        search_port=search_adapter,
        chunk_port=chunk_adapter,
    )
