from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from knowledgenexus.presentation.api.v1 import router as retrieve_router


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
