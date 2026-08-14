from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from knowledgenexus.presentation.middleware.cors import get_cors_middleware_kwargs
from knowledgenexus.presentation.api.v1 import documents_router, health_router, ingest_job_router, retrieve_router, store_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from knowledgenexus.shared.config.settings import get_settings
    from knowledgenexus.shared.di.container import init_container, shutdown_container
    from knowledgenexus.presentation.api.v1.ingest_job import (
        CONFLUENCE_INGEST_WORKER_COUNT,
        confluence_ingest_worker,
    )

    settings = get_settings()
    container = await init_container(settings)

    # Long-running consumers for the Confluence ingest queue — live for the
    # whole process, so submitted jobs keep draining even across many
    # requests without blocking request handlers.
    workers = [
        asyncio.create_task(confluence_ingest_worker(container))
        for _ in range(CONFLUENCE_INGEST_WORKER_COUNT)
    ]
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
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

# Serve demo/ static files so LAN machines can access index.html via browser
# Access: http://<server-lan-ip>:8000/demo → serves demo/index.html
_DEMO_DIR = Path(__file__).resolve().parents[4] / "demo"

if _DEMO_DIR.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_DEMO_DIR), html=True), name="demo")
