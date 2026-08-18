from .documents import router as documents_router
from .health import router as health_router
from .ingest_job import router as ingest_job_router
from .retrieve import router as retrieve_router
from .store import router as store_router

__all__ = [
    "documents_router",
    "health_router",
    "ingest_job_router",
    "retrieve_router",
    "store_router",
]
