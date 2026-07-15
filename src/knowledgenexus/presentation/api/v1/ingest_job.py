from uuid import uuid4
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.shared.di.container import AppContainer, get_container
from knowledgenexus.presentation.api.v1.schemas.ingest_job_schema import (
    CreateIngestJobRequest,
    IngestJobResponse,
    UpdateIngestJobRequest,
)

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
