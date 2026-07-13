from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from knowledgenexus.presentation.api.v1 import health_router, retrieve_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from knowledgenexus.shared.config.settings import get_settings
    from knowledgenexus.shared.di.container import init_container, shutdown_container

    settings = get_settings()
    await init_container(settings)
    yield
    await shutdown_container()


app = FastAPI(
    title="KnowledgeNexus API",
    version="0.1.0",
    description="RAG platform — modular monolith (foundation / indexing / retrieval / chat)",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(retrieve_router)
