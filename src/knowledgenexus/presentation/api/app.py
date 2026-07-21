from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from knowledgenexus.presentation.middleware.cors import get_cors_middleware_kwargs
from knowledgenexus.presentation.api.v1 import documents_router, health_router, ingest_job_router, retrieve_router, store_router


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

# CORS — allow external websites (browser) to call this API
app.add_middleware(CORSMiddleware, **get_cors_middleware_kwargs())

app.include_router(health_router)
app.include_router(retrieve_router)
app.include_router(documents_router)
app.include_router(store_router)
app.include_router(ingest_job_router)
