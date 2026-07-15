from fastapi import APIRouter, Depends

from knowledgenexus.shared.di.container import AppContainer, get_container
from knowledgenexus.shared.config.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1", tags=["health"])


def _container() -> AppContainer:
    return get_container()


@router.get("/health")
async def health(
    settings: Settings = Depends(get_settings),
    container: AppContainer = Depends(_container),
) -> dict[str, object]:
    sqlite_ok = False
    qdrant_ok = False
    try:
        async with container.engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        sqlite_ok = True
    except Exception:
        sqlite_ok = False

    try:
        qdrant_ok = await container.vector_store.health_check()
    except Exception:
        qdrant_ok = False

    overall = "ok" if sqlite_ok and qdrant_ok else "degraded"
    return {
        "status": overall,
        "storage_mode": settings.storage_mode.value,
        "sqlite": "ok" if sqlite_ok else "error",
        "qdrant": "ok" if qdrant_ok else "error",
        "qdrant_url": settings.qdrant_url,
    }
