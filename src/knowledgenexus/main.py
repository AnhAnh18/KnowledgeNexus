from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from knowledgenexus.presentation import router as retrieve_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from knowledgenexus.shared.config.settings import get_settings
    from knowledgenexus.shared.di import init_container, shutdown_container

    settings = get_settings()
    await init_container(settings)
    yield
    await shutdown_container()


app = FastAPI(
    title="KnowledgeNexus",
    description="Semantic search & document management API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(retrieve_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def get_retrieve_chunks_use_case():
    from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase
    from knowledgenexus.retrieval.infrastructure.query_adapters import (
        IndexingChunkAdapter,
        IndexingEmbedderAdapter,
        IndexingSearchAdapter,
    )
    from knowledgenexus.shared.di import get_container

    container = get_container()

    embedder_adapter = IndexingEmbedderAdapter(container.embedder)
    search_adapter = IndexingSearchAdapter(container.vector_store)
    chunk_adapter = IndexingChunkAdapter(container.chunk_repo)

    return RetrieveChunksUseCase(
        query_embedder=embedder_adapter,
        search_port=search_adapter,
        chunk_port=chunk_adapter,
    )
