import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from knowledgenexus.foundation.domain.rules.confluence_url import (
    ConfluenceUrlParseError,
    parse_confluence_page_id,
)
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.shared.di.container import AppContainer, get_container
from knowledgenexus.presentation.api.v1.schemas.ingest_job_schema import (
    CreateIngestJobRequest,
    IngestConfluenceUrlRequest,
    IngestJobResponse,
    UpdateIngestJobRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ingest-jobs", tags=["ingest-jobs"])


def _container() -> AppContainer:
    return get_container()


def _to_response(job: IngestJob) -> IngestJobResponse:
    return IngestJobResponse(
        id=job.id,
        source_type=job.source_type,
        status=job.status,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        stats=job.stats,
    )


@router.post("", response_model=IngestJobResponse, status_code=status.HTTP_201_CREATED)
async def create_ingest_job(
    body: CreateIngestJobRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    job = IngestJob(
        id=str(uuid4()),
        source_type=body.source_type,
        status=IngestJobStatus.PENDING,
        started_at=datetime.now(UTC),
        stats=body.stats,
    )
    await container.ingest_job_repo.create(job)
    return _to_response(job)


@dataclass(frozen=True)
class ConfluenceIngestTask:
    """One queued unit of work for `confluence_ingest_worker`."""

    job_id: str
    url: str


# Number of jobs processed concurrently by the queue worker(s). Kept at 1
# by default: BgeM3Embedder is a single shared model instance, so running
# more than one heavy embedding job at a time buys little real throughput
# while making memory/CPU contention harder to reason about. Raise this if
# ingestion needs to scale beyond one job at a time.
CONFLUENCE_INGEST_WORKER_COUNT = 1


@router.post(
    "/confluence-pages",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_page_ingest_job(
    body: IngestConfluenceUrlRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    try:
        page_id = parse_confluence_page_id(body.url)
    except ConfluenceUrlParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    job = IngestJob(
        id=str(uuid4()),
        source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.PENDING,
        started_at=datetime.now(UTC),
        stats={"url": body.url, "page_id": page_id},
    )
    await container.ingest_job_repo.create(job)
    # Enqueue instead of firing a bare BackgroundTask: this lets many jobs be
    # submitted back-to-back — they stay PENDING and wait their turn in the
    # queue — instead of each request racing to run its own ingest
    # immediately. The request returns right away regardless of queue depth.
    await container.get_confluence_ingest_queue().put(
        ConfluenceIngestTask(job_id=job.id, url=body.url)
    )
    return _to_response(job)


async def confluence_ingest_worker(container: AppContainer) -> None:
    """Long-running consumer: pulls one queued job at a time and runs it.

    Started as a background asyncio task per FastAPI app lifespan (see
    `presentation/api/app.py`), so it lives for the whole process lifetime
    and keeps consuming `container.get_confluence_ingest_queue()` without
    blocking request handlers.
    """
    queue = container.get_confluence_ingest_queue()
    while True:
        task = await queue.get()
        try:
            await _run_confluence_page_ingest_job(task.job_id, task.url, container)
        except Exception:
            logger.exception("Unhandled error processing ingest job %s", task.job_id)
        finally:
            queue.task_done()


async def _run_confluence_page_ingest_job(job_id: str, url: str, container: AppContainer) -> None:
    """Fetch the page live, chunk it, embed it, and store it."""
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        logger.warning("Ingest job %s disappeared before it could run", job_id)
        return

    job.status = IngestJobStatus.RUNNING
    await container.ingest_job_repo.update(job)

    try:
        # First call lazily builds the tokenizer + BGE-M3 embedder (loading
        # a multi-GB model from disk) — genuinely blocking, synchronous work.
        # Run it off the event loop so other requests (and other queued
        # jobs' status polling) stay responsive while it loads.
        ingestor = await asyncio.to_thread(container.get_confluence_page_ingestor)
        result = await ingestor.execute(url=url)
        job.status = IngestJobStatus.COMPLETED
        job.stats = {
            **job.stats,
            "status": result.status,
            "chunks_ingested": result.chunks_ingested,
            "chunks_failed": result.chunks_failed,
            "embedding_model": result.embedding_model,
        }
    except Exception as exc:
        logger.exception("Confluence page ingest job %s failed", job_id)
        job.status = IngestJobStatus.FAILED
        job.error = str(exc)
    job.completed_at = datetime.now(UTC)
    await container.ingest_job_repo.update(job)


@router.get("/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(
    job_id: str,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingest job '{job_id}' not found",
        )
    return _to_response(job)


@router.patch("/{job_id}", response_model=IngestJobResponse)
async def update_ingest_job(
    job_id: str,
    body: UpdateIngestJobRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingest job '{job_id}' not found",
        )

    if body.status is not None:
        job.status = body.status
    if body.completed_at is not None:
        job.completed_at = body.completed_at
    if body.error is not None:
        job.error = body.error
    job.stats = body.stats

    await container.ingest_job_repo.update(job)
    return _to_response(job)
