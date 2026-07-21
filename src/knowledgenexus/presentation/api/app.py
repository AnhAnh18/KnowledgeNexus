from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from knowledgenexus.presentation.middleware.cors import get_cors_middleware_kwargs
from knowledgenexus.presentation.api.v1 import chat_router, documents_router, health_router, ingest_job_router, retrieve_router, store_router


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
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(store_router)
app.include_router(ingest_job_router)

# Serve demo/ static files so LAN machines can access index.html via browser
# Access: http://<server-lan-ip>:8000/demo → serves demo/index.html
_DEMO_DIR = Path(__file__).resolve().parents[4] / "demo"

if _DEMO_DIR.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_DEMO_DIR), html=True), name="demo")
