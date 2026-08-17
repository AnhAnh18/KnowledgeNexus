import logging
import asyncio
import hashlib
import ipaddress
from uuid import uuid4
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from knowledgenexus.foundation.domain.rules.confluence_url import (
    ConfluenceUrlParseError,
    parse_confluence_page_id,
)
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.indexing.application.use_cases.ingest_confluence_subtree_from_url import (
    ConfluenceSubtreeIngestError,
)
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


def _submission_key(url: object) -> str:
    if type(url) is not str or not url or any(char.isspace() for char in url):
        raise ValueError
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or _is_ip_literal(parsed.hostname)
        ):
            raise ValueError
        normalized = f"https://{parsed.netloc.lower()}{parsed.path}?{parsed.query}"
    except ValueError:
        raise ValueError from None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _canonical_key(base_url: str, space_key: str, page_id: str) -> str:
    return hashlib.sha256(
        f"{base_url}|{space_key}|{page_id}".encode("ascii")
    ).hexdigest()


async def _set_progress(job: IngestJob, container: AppContainer, payload: object) -> None:
    if type(payload) is not dict or type(payload.get("phase")) is not str:
        raise ValueError("progress")
    allowed = {
        "resolving_url", "inventory", "capture_pages", "process_pages",
        "capture_drawio", "publish_packet", "indexing_validate", "indexing_embed",
        "indexing_store", "completed",
    }
    if payload["phase"] not in allowed:
        raise ValueError("progress")
    for key, value in payload.items():
        if key != "phase" and (type(value) is not int or value < 0):
            raise ValueError("progress")
    current = dict(job.stats)
    current.update(payload)
    job.stats = current
    await container.ingest_job_repo.update(job)


async def _resolve_canonical_url(url: str, container: AppContainer) -> tuple[str, str, str]:
    """Resolve a submitted URL in the worker, before any subtree crawl."""
    from knowledgenexus.foundation.cli.export_confluence_url_text_snapshot import (
        TextSnapshotOperatorError, parse_canonical_page_url,
    )
    # Short-link resolution performs an authenticated redirect read.  Bind the
    # submitted origin to the configured Confluence origin *before* invoking
    # that resolver so a browser cannot turn the PAT into an SSRF credential.
    try:
        if type(container.settings.confluence_base_url) is not str:
            raise ConfluenceSubtreeIngestError("configuration", resumable=False)
        submitted = urlsplit(url)
        configured = urlsplit(container.settings.confluence_base_url)
        if (
            submitted.scheme != "https" or configured.scheme != "https"
            or submitted.hostname is None or configured.hostname is None
            or _is_ip_literal(submitted.hostname) or _is_ip_literal(configured.hostname)
            or submitted.hostname.lower() != configured.hostname.lower()
            or (submitted.port or 443) != (configured.port or 443)
        ):
            raise ConfluenceSubtreeIngestError("url_origin", resumable=False)
    except ValueError:
        raise ConfluenceSubtreeIngestError("url_origin", resumable=False) from None
    try:
        resolved = await asyncio.to_thread(parse_canonical_page_url, url)
    except TextSnapshotOperatorError as exc:
        raise ConfluenceSubtreeIngestError(exc.category, resumable=False) from None
    actual = urlsplit(resolved[0])
    if (
        configured.scheme != "https" or actual.scheme != "https"
        or configured.hostname is None or actual.hostname is None
        or _is_ip_literal(actual.hostname)
        or configured.hostname.lower() != actual.hostname.lower()
        or (configured.port or 443) != (actual.port or 443)
    ):
        raise ConfluenceSubtreeIngestError("url_origin", resumable=False)
    return resolved


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


@router.post(
    "/confluence-pages",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_page_ingest_job(
    body: IngestConfluenceUrlRequest,
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(_run_confluence_page_ingest_job, job.id, body.url, container)
    return _to_response(job)


@router.post(
    "/confluence-subtrees",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_subtree_ingest_job(
    body: IngestConfluenceUrlRequest,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    try:
        submission_key = _submission_key(body.url)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Confluence URL")
    job = IngestJob(
        id=str(uuid4()), source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.PENDING, started_at=datetime.now(UTC),
        # Never persist the submitted URL or filesystem workspace in public job stats.
        stats={"phase": "resolving_url", "resumable": False}, active_key=submission_key,
    )
    try:
        owner, created = await container.ingest_job_repo.create_or_get_active(job)
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ingest job unavailable")
    if not created:
        return _to_response(owner)
    background_tasks.add_task(_run_confluence_subtree_ingest_job, job.id, body.url, container)
    return _to_response(job)


async def _run_confluence_page_ingest_job(job_id: str, url: str, container: AppContainer) -> None:
    """Background job: fetch the page live, chunk it, embed it, and store it."""
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        logger.warning("Ingest job %s disappeared before it could run", job_id)
        return

    job.status = IngestJobStatus.RUNNING
    await container.ingest_job_repo.update(job)
    try:
        ingestor = container.get_confluence_page_ingestor()
        result = await ingestor.execute(url=url)
        job.status = IngestJobStatus.COMPLETED
        job.stats = {
            **job.stats,
            "status": result.status,
            "chunks_ingested": result.chunks_ingested,
            "chunks_failed": result.chunks_failed,
            "embedding_model": result.embedding_model,
        }
    except Exception:
        logger.exception("Confluence page ingest job %s failed", job_id)
        job.status = IngestJobStatus.FAILED
        job.error = "ingest_failed"
    job.completed_at = datetime.now(UTC)
    await container.ingest_job_repo.update(job)


async def _run_confluence_subtree_ingest_job(job_id: str, url: str, container: AppContainer) -> None:
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        return
    job.status = IngestJobStatus.RUNNING
    await container.ingest_job_repo.update(job)
    try:
        await _set_progress(job, container, {"phase": "resolving_url"})
        base_url, space_key, page_id = await _resolve_canonical_url(url, container)
        canonical_key = _canonical_key(base_url, space_key, page_id)
        if canonical_key != job.active_key:
            job.active_key = canonical_key
            try:
                await container.ingest_job_repo.update(job)
            except Exception:
                existing = await container.ingest_job_repo.get_by_active_key(canonical_key)
                job.active_key = None
                job.status = IngestJobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error = "duplicate_active_job" if existing is not None else "job_registry"
                job.stats = {"phase": "failed", "resumable": False}
                await container.ingest_job_repo.update(job)
                return
        canonical_url = f"{base_url}/spaces/{space_key}/pages/{page_id}"
        ingestor = container.get_confluence_subtree_ingestor()

        async def report(payload: object) -> None:
            await _set_progress(job, container, payload)

        result = await ingestor.execute(
            job_id=job.id, canonical_url=canonical_url, report_progress=report,
        )
        job.status = IngestJobStatus.COMPLETED
        job.active_key = None
        job.completed_at = datetime.now(UTC)
        job.stats = {
            "phase": "completed", "resumable": False,
            "chunks_ingested": result.chunks_ingested,
            "chunks_failed": result.chunks_failed,
        }
    except ConfluenceSubtreeIngestError as exc:
        job.status = IngestJobStatus.FAILED
        job.active_key = None
        job.completed_at = datetime.now(UTC)
        job.error = exc.category
        job.stats = {"phase": "failed", "resumable": exc.resumable}
    except Exception:
        job.status = IngestJobStatus.FAILED
        job.active_key = None
        job.completed_at = datetime.now(UTC)
        job.error = "unexpected"
        job.stats = {"phase": "failed", "resumable": True}
    await container.ingest_job_repo.update(job)


@router.post("/{job_id}/resume", response_model=IngestJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def resume_confluence_subtree_ingest_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingest job not found")
    if job.status is not IngestJobStatus.FAILED or job.stats.get("resumable") is not True:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ingest job is not resumable")
    try:
        ingestor = container.get_confluence_subtree_ingestor()
        canonical_url = ingestor.resume_url(job_id=job.id)
        base_url, space_key, page_id = await _resolve_canonical_url(canonical_url, container)
        job.active_key = _canonical_key(base_url, space_key, page_id)
        job.status = IngestJobStatus.PENDING
        job.completed_at = None
        job.error = None
        job.stats = {"phase": "resolving_url", "resumable": False}
        await container.ingest_job_repo.update(job)
    except ConfluenceSubtreeIngestError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.category)
    except Exception:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume unavailable")
    background_tasks.add_task(_run_confluence_subtree_ingest_job, job.id, canonical_url, container)
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
