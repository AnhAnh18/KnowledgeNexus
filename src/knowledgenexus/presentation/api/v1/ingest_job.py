import logging
import asyncio
import hashlib
import json
import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status

from knowledgenexus.foundation.domain.rules.confluence_url import (
    ConfluenceUrlParseError,
    parse_confluence_page_id,
)
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.indexing.application.use_cases.ingest_confluence_subtree_from_url import (
    ConfluenceSubtreeIngestError,
)
from knowledgenexus.indexing.application.use_cases.confluence_sync_state import (
    RootIdentity,
    find_baseline_workspace,
    published_packet_dir,
)
from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import document_uuid
from knowledgenexus.indexing.application.use_cases.preview_confluence_sync import preview_sync
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


@dataclass(frozen=True)
class ConfluenceIngestTask:
    """One queued unit of work for `confluence_ingest_worker`.

    `kind` selects the runner: a single page (`"page"`), a whole subtree
    (`"subtree"`), a read-only sync preview (`"sync_preview"`), or a sync that
    reconciles an already indexed root (`"sync_apply"`).  All kinds share one
    queue so submissions are drained in arrival order regardless of which
    endpoint created them.
    """

    kind: str
    job_id: str
    url: str


# Number of jobs processed concurrently by the queue worker(s). Kept at 1
# by default: BgeM3Embedder is a single shared model instance, so running
# more than one heavy embedding job at a time buys little real throughput
# while making memory/CPU contention harder to reason about. Raise this if
# ingestion needs to scale beyond one job at a time.
CONFLUENCE_INGEST_WORKER_COUNT = 1

# Sync previews build throwaway inventory state. They are kept under their own
# directory inside the snapshot root so baseline discovery, which scans that
# root for published packets, never has to reason about them.
_SYNC_PREVIEW_DIR = ".sync-preview"


async def confluence_ingest_worker(container: AppContainer) -> None:
    """Long-running consumer: pulls one queued job at a time and runs it.

    Started as a background asyncio task per FastAPI app lifespan (see
    `presentation/api/app.py`), so it lives for the whole process lifetime
    and keeps consuming `container.get_confluence_ingest_queue()` without
    blocking request handlers.  Jobs sit in the queue as PENDING ("waiting"
    in the UI) and only flip to RUNNING when a worker picks them up.
    """
    queue = container.get_confluence_ingest_queue()
    while True:
        task = await queue.get()
        try:
            if task.kind == "subtree":
                await _run_confluence_subtree_ingest_job(task.job_id, task.url, container)
            elif task.kind == "sync_preview":
                await _run_confluence_sync_preview_job(task.job_id, task.url, container)
            elif task.kind == "sync_apply":
                await _run_confluence_sync_apply_job(task.job_id, task.url, container)
            else:
                await _run_confluence_page_ingest_job(task.job_id, task.url, container)
        except Exception:
            logger.exception("Unhandled error processing ingest job %s", task.job_id)
        finally:
            queue.task_done()


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


class _IngestJobCancelled(Exception):
    """Raised inside the progress callback to unwind a job an operator stopped."""


# Job ids an operator asked to stop. A running job cannot be killed outright:
# the crawl is a blocking call in a worker thread, and Python cannot interrupt
# one. Instead the progress callback -- which Foundation invokes at every phase
# boundary and every capture batch -- raises, which unwinds the run. The set is
# per-process and deliberately not persisted: a restart already ends the run.
_CANCEL_REQUESTED: set[str] = set()


async def _set_progress(job: IngestJob, container: AppContainer, payload: object) -> None:
    # Checked here because this is the one place the crawl hands control back
    # to us often enough to stop it promptly.
    if job.id in _CANCEL_REQUESTED:
        raise _IngestJobCancelled(job.id)
    if type(payload) is not dict or type(payload.get("phase")) is not str:
        raise ValueError("progress")
    allowed = {
        "resolving_url", "inventory", "capture_pages", "process_pages",
        "capture_drawio", "export_packet", "publish_packet", "indexing_validate",
        "indexing_embed", "indexing_store", "completed",
        # Sync-only phases: the diff decision, and the deletion of pages the
        # source no longer has.
        "sync_plan", "tombstone",
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


def _require_configured_ingest(container: AppContainer) -> None:
    """Refuse a submission the server cannot possibly run.

    Without this the job is accepted, queued, and only discovered to be
    unrunnable when a worker reaches it -- the operator waits, then gets a
    bare "configuration" with no clue which setting is missing.
    """
    problems = container.confluence_ingest_config_problems()
    if problems:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Confluence ingest is not configured: "
                + "; ".join(problems)
                + ". Set these in your .env (see .env.example) and restart the server."
            ),
        )


# Phases reached only once Foundation has created the workspace on disk.
# Stopping at or after one of these leaves something to resume from; stopping
# before it does not, so those jobs are cancelled outright rather than paused.
_RESUMABLE_FROM_PHASES = frozenset({
    "inventory", "capture_pages", "process_pages", "capture_drawio",
    "export_packet", "publish_packet", "indexing_validate", "indexing_embed",
    "indexing_store", "sync_plan", "tombstone",
})


def _mark_stopped(job: IngestJob) -> None:
    """Stop the job on request, keeping the progress it had already made.

    Whether it can be resumed is not a preference but a fact about the disk:
    a job stopped while still resolving its URL has no Foundation workspace,
    and `resume_url` would fail on it. Only jobs that got far enough to own a
    workspace are paused; the rest are simply cancelled.
    """
    previous = dict(job.stats) if isinstance(job.stats, dict) else {}
    stopped_at = previous.get("phase")
    resumable = isinstance(stopped_at, str) and stopped_at in _RESUMABLE_FROM_PHASES
    job.status = IngestJobStatus.PAUSED if resumable else IngestJobStatus.CANCELLED
    job.active_key = None
    job.completed_at = datetime.now(UTC)
    job.error = None
    previous.update({
        "phase": "paused" if resumable else "cancelled",
        "resumable": resumable,
    })
    if isinstance(stopped_at, str) and stopped_at not in {"cancelled", "paused", "queued"}:
        previous["failed_phase"] = stopped_at
    job.stats = previous


def _mark_failed(job: IngestJob, *, category: str, resumable: bool) -> None:
    """Fail the job while keeping what it had already achieved.

    Overwriting `stats` wholesale threw away the phase the job died in and
    every counter it had reported, so the only way to find out where a job
    broke was a server-side traceback -- unavailable to anyone driving the UI
    from another machine. Keep the progress and record where it stopped.
    """
    previous = dict(job.stats) if isinstance(job.stats, dict) else {}
    failed_phase = previous.get("phase")
    job.status = IngestJobStatus.FAILED
    job.active_key = None
    job.completed_at = datetime.now(UTC)
    job.error = category
    previous.update({"phase": "failed", "resumable": resumable})
    if isinstance(failed_phase, str) and failed_phase not in {"failed", "queued"}:
        previous["failed_phase"] = failed_phase
    job.stats = previous


async def _resolve_canonical_url(url: str, container: AppContainer) -> tuple[str, str, str]:
    """Resolve a submitted URL in the worker, before any subtree crawl."""
    from knowledgenexus.foundation.cli.export_confluence_url_text_snapshot import (
        TextSnapshotOperatorError, parse_canonical_page_url,
        # The same two resolvers the CLI `run()` boundary installs; without
        # them an opaque short link (/x/TOKEN, or /pages/ID with no space)
        # can only fail as "url_requires_resolution".
        _resolve_short_link, _resolve_short_space_key,
    )
    from knowledgenexus.indexing.application.use_cases.ingest_confluence_subtree_from_url import (
        _FOUNDATION_ENVIRONMENT_LOCK,
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
    def resolve() -> tuple[str, str, str]:
        # The resolvers read the PAT from the process environment, which is the
        # contract the CLI relies on -- but Settings loads it from .env without
        # exporting it.  Publish it only for the duration of the call, under the
        # same lock the subtree ingestor takes when it does this for the crawl.
        pat = container.settings.confluence_pat
        with _FOUNDATION_ENVIRONMENT_LOCK:
            prior_pat = os.environ.get("CONFLUENCE_PAT")
            if type(pat) is str and pat:
                os.environ["CONFLUENCE_PAT"] = pat
            try:
                return parse_canonical_page_url(
                    url,
                    short_space_resolver=_resolve_short_space_key,
                    short_link_resolver=_resolve_short_link,
                )
            finally:
                if prior_pat is None:
                    os.environ.pop("CONFLUENCE_PAT", None)
                else:
                    os.environ["CONFLUENCE_PAT"] = prior_pat

    try:
        resolved = await asyncio.to_thread(resolve)
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
        ConfluenceIngestTask(kind="page", job_id=job.id, url=body.url)
    )
    return _to_response(job)


@router.post(
    "/confluence-subtrees",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_subtree_ingest_job(
    body: IngestConfluenceUrlRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    _require_configured_ingest(container)
    try:
        submission_key = _submission_key(body.url)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Confluence URL")
    job = IngestJob(
        id=str(uuid4()), source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.PENDING, started_at=datetime.now(UTC),
        # "queued" is the waiting state the UI shows until a worker picks the job up.
        stats={"phase": "queued", "resumable": False, "url": body.url, "kind": "subtree"},
        active_key=submission_key,
    )
    try:
        owner, created = await container.ingest_job_repo.create_or_get_active(job)
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ingest job unavailable")
    if not created:
        return _to_response(owner)
    await container.get_confluence_ingest_queue().put(
        ConfluenceIngestTask(kind="subtree", job_id=job.id, url=body.url)
    )
    return _to_response(job)


@router.post(
    "/confluence-subtrees/sync-preview",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_sync_preview_job(
    body: IngestConfluenceUrlRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    """Queue a read-only inventory diff for a previously ingested URL."""
    _require_configured_ingest(container)
    try:
        submission_key = "sync-preview:" + _submission_key(body.url)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Confluence URL",
        )
    job = IngestJob(
        id=str(uuid4()), source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.PENDING, started_at=datetime.now(UTC),
        stats={
            "phase": "queued", "resumable": False, "url": body.url,
            "kind": "sync_preview", "sync_preview": True,
        },
        active_key=hashlib.sha256(submission_key.encode("ascii")).hexdigest(),
    )
    try:
        owner, created = await container.ingest_job_repo.create_or_get_active(job)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="sync preview unavailable",
        )
    if not created:
        return _to_response(owner)
    await container.get_confluence_ingest_queue().put(
        ConfluenceIngestTask(kind="sync_preview", job_id=job.id, url=body.url)
    )
    return _to_response(job)


@router.post(
    "/confluence-subtrees/sync-apply",
    response_model=IngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_confluence_sync_apply_job(
    body: IngestConfluenceUrlRequest,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    """Queue a sync that reconciles the index with the live subtree.

    Unlike a plain re-ingest this also removes pages the source no longer has,
    and it embeds only the pages whose version moved -- so it is the only
    submission that can leave the index *smaller* than it found it.  It shares
    the subtree submission key, so a sync and an ingest of the same root
    cannot run at the same time.
    """
    _require_configured_ingest(container)
    try:
        submission_key = _submission_key(body.url)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Confluence URL",
        )
    job = IngestJob(
        id=str(uuid4()), source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.PENDING, started_at=datetime.now(UTC),
        stats={"phase": "queued", "resumable": False, "url": body.url, "kind": "sync_apply"},
        active_key=submission_key,
    )
    try:
        owner, created = await container.ingest_job_repo.create_or_get_active(job)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="sync unavailable",
        )
    if not created:
        return _to_response(owner)
    await container.get_confluence_ingest_queue().put(
        ConfluenceIngestTask(kind="sync_apply", job_id=job.id, url=body.url)
    )
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
    except Exception:
        logger.exception("Confluence page ingest job %s failed", job_id)
        job.status = IngestJobStatus.FAILED
        job.error = "ingest_failed"
    job.completed_at = datetime.now(UTC)
    await container.ingest_job_repo.update(job)


def _packet_root_page(workspace: Path, job_id: str) -> tuple[str | None, str | None]:
    """Read the root page's title and URL from the packet a job published.

    The first documents row is the root by construction. Only that line is
    read: a 5k-page packet's documents.jsonl is far too large to pull into
    memory for two strings.
    """
    packet = published_packet_dir(workspace)
    if packet is None:
        return None, None
    try:
        with open(packet / "documents.jsonl", encoding="utf-8") as stream:
            row = json.loads(stream.readline())
        title, url = row.get("title"), row.get("url")
    except Exception:
        logger.warning("Could not read root page title from documents.jsonl for job %s", job_id)
        return None, None
    return (
        title if isinstance(title, str) else None,
        url if isinstance(url, str) else None,
    )


async def _run_confluence_subtree_ingest_job(job_id: str, url: str, container: AppContainer) -> None:
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        return
    # A job cancelled while it sat in the queue must never start.
    if job.status in (IngestJobStatus.CANCELLED, IngestJobStatus.PAUSED) or job.id in _CANCEL_REQUESTED:
        _CANCEL_REQUESTED.discard(job.id)
        _mark_stopped(job)
        await container.ingest_job_repo.update(job)
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
        ingestor = await asyncio.to_thread(container.get_confluence_subtree_ingestor)
        async def report(payload: object) -> None:
            await _set_progress(job, container, payload)
        result = await ingestor.execute(job_id=job.id, canonical_url=canonical_url, report_progress=report)
        job.status = IngestJobStatus.COMPLETED
        job.active_key = None
        job.completed_at = datetime.now(UTC)
        root_title, root_url = _packet_root_page(
            container.confluence_snapshot_root() / job.id, job.id
        )
        job.stats = {
            **job.stats, "phase": "completed", "resumable": False,
            "kind": "subtree", "canonical_url": canonical_url,
            "chunks_ingested": result.chunks_ingested,
            "chunks_failed": result.chunks_failed,
        }
        if root_title:
            job.stats["title"] = root_title
        if root_url and "url" not in job.stats:
            job.stats["url"] = root_url
    except _IngestJobCancelled:
        _mark_stopped(job)
    except ConfluenceSubtreeIngestError as exc:
        if job.id in _CANCEL_REQUESTED:
            _mark_stopped(job)
        else:
            _mark_failed(job, category=exc.category, resumable=exc.resumable)
    except RuntimeError:
        logger.exception("Confluence subtree ingest job %s is misconfigured", job_id)
        _mark_failed(job, category="configuration", resumable=False)
    except Exception:
        logger.exception("Confluence subtree ingest job %s failed unexpectedly", job_id)
        _mark_failed(job, category="unexpected", resumable=True)
    finally:
        _CANCEL_REQUESTED.discard(job.id)
    await container.ingest_job_repo.update(job)


async def _resolve_root_identity(url: str, container: AppContainer) -> RootIdentity:
    base_url, space_key, page_id = await _resolve_canonical_url(url, container)
    return RootIdentity(base_url, space_key, page_id)


def _baseline_workspace(
    identity: RootIdentity, container: AppContainer, *, exclude: str
) -> Path | None:
    """Locate the packet a sync should diff against.

    Discovery reads the snapshot root rather than the job table on purpose:
    the baseline is whatever was last *published on disk* for this root, so it
    still resolves after the job database has been reset or pruned.
    """
    return find_baseline_workspace(
        snapshot_root=container.confluence_snapshot_root(),
        identity=identity,
        exclude=frozenset({exclude}),
    )


async def _run_confluence_sync_preview_job(job_id: str, url: str, container: AppContainer) -> None:
    """Inventory a previously ingested root and report a non-mutating diff."""
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        return
    job.status = IngestJobStatus.RUNNING
    await container.ingest_job_repo.update(job)
    try:
        await _set_progress(job, container, {"phase": "inventory"})
        identity = await _resolve_root_identity(url, container)
        snapshot_root = container.confluence_snapshot_root()
        # Preview workspaces are throwaway inventory state, not snapshots, so
        # they live in their own subdirectory: baseline discovery scans the
        # snapshot root and must never mistake one for a published packet.
        workspace = snapshot_root / _SYNC_PREVIEW_DIR / job.id
        result = await asyncio.to_thread(
            preview_sync,
            url=identity.canonical_url,
            workspace=workspace,
            snapshot_root=snapshot_root,
            max_pages=container.settings.confluence_max_pages,
            reliability_profile=container.settings.confluence_reliability_profile_path,
            tokenizer_assets_dir=(
                Path(container.settings.embedding_model_path)
                if container.settings.embedding_model_path else None
            ),
            confluence_pat=container.settings.confluence_pat,
        )
        job.stats = {
            **job.stats, **result, "url": identity.canonical_url,
            "kind": "sync_preview", "resumable": False,
            # A preview never mutates the index, so it always *completes*; a
            # missing baseline is an answer ("this root has no packet yet"),
            # not a failure the operator has to retry.
            "phase": "completed",
        }
        job.status = IngestJobStatus.COMPLETED
        job.error = None
    except ConfluenceSubtreeIngestError as exc:
        logger.warning("Sync preview job %s could not resolve its root: %s", job_id, exc.category)
        _mark_failed(job, category=exc.category, resumable=False)
    except Exception:
        logger.exception("Confluence sync preview job %s failed", job_id)
        _mark_failed(job, category="sync_preview", resumable=False)
    job.completed_at = datetime.now(UTC)
    job.active_key = None
    await container.ingest_job_repo.update(job)


async def _run_confluence_sync_apply_job(job_id: str, url: str, container: AppContainer) -> None:
    """Re-publish a root and reconcile the index, tombstones included."""
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        return
    # A job cancelled while it sat in the queue must never start.
    if job.status in (IngestJobStatus.CANCELLED, IngestJobStatus.PAUSED) or job.id in _CANCEL_REQUESTED:
        _CANCEL_REQUESTED.discard(job.id)
        _mark_stopped(job)
        await container.ingest_job_repo.update(job)
        return
    job.status = IngestJobStatus.RUNNING
    await container.ingest_job_repo.update(job)
    try:
        await _set_progress(job, container, {"phase": "resolving_url"})
        identity = await _resolve_root_identity(url, container)
        baseline = _baseline_workspace(identity, container, exclude=job.id)
        ingestor = await asyncio.to_thread(container.get_confluence_subtree_ingestor)

        async def report(payload: object) -> None:
            await _set_progress(job, container, payload)

        async def delete_page(page_id: str, document_id: str) -> None:
            # Two passes on purpose. Deleting by document id is the exact
            # cascade -- chunks, vectors and the documents row -- but it only
            # reaches records that carry the derived document id. The
            # source_id pass also sweeps chunks written for this page before
            # that id existed, so a tombstone leaves nothing behind either way.
            await container.chunk_storage.delete_by_source_id(SourceType.CONFLUENCE, page_id)
            await container.chunk_storage.delete_by_document_id(str(document_uuid(document_id)))

        result = await ingestor.execute_sync(
            job_id=job.id, canonical_url=identity.canonical_url, report_progress=report,
            baseline_workspace=baseline, delete_page=delete_page,
        )
        job.status = IngestJobStatus.COMPLETED
        job.active_key = None
        job.error = None
        job.completed_at = datetime.now(UTC)
        job.stats = {
            **job.stats, **result.stats(), "phase": "completed", "resumable": False,
            "kind": "sync_apply", "url": identity.canonical_url,
            "canonical_url": identity.canonical_url,
            "baseline_workspace": str(baseline) if baseline else None,
        }
    except _IngestJobCancelled:
        _mark_stopped(job)
    except ConfluenceSubtreeIngestError as exc:
        if job.id in _CANCEL_REQUESTED:
            _mark_stopped(job)
        else:
            _mark_failed(job, category=exc.category, resumable=exc.resumable)
    except RuntimeError:
        logger.exception("Confluence sync job %s is misconfigured", job_id)
        _mark_failed(job, category="configuration", resumable=False)
    except Exception:
        logger.exception("Confluence sync job %s failed unexpectedly", job_id)
        _mark_failed(job, category="unexpected", resumable=True)
    finally:
        _CANCEL_REQUESTED.discard(job.id)
    await container.ingest_job_repo.update(job)


@router.post("/{job_id}/cancel", response_model=IngestJobResponse)
async def cancel_confluence_subtree_ingest_job(
    job_id: str,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    """Stop a queued or running ingest job.

    A queued job settles immediately as CANCELLED -- it never started, so it
    has no workspace and nothing to resume from.

    A running job cannot be killed: the crawl is a blocking call in a worker
    thread. It is flagged instead and unwinds at the next phase boundary (or
    the next capture batch), so expect a short delay rather than an instant
    halt; it stays RUNNING until then. Once it stops it becomes PAUSED and can
    be resumed, because the Foundation workspace it built is still on disk.
    """
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingest job not found")
    if job.status not in (IngestJobStatus.PENDING, IngestJobStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ingest job is already {job.status.value}",
        )

    _CANCEL_REQUESTED.add(job.id)
    if job.status is IngestJobStatus.PENDING:
        # Still in the queue: settle it now. The worker checks the status when
        # it dequeues, so it will skip this job rather than start it.
        _mark_stopped(job)
        await container.ingest_job_repo.update(job)
    return _to_response(job)


@router.post("/{job_id}/resume", response_model=IngestJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def resume_confluence_subtree_ingest_job(
    job_id: str,
    container: AppContainer = Depends(_container),
) -> IngestJobResponse:
    _require_configured_ingest(container)
    job = await container.ingest_job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingest job not found")
    # PAUSED joins FAILED here: an operator stopping a crawl leaves exactly the
    # same half-built workspace a resumable failure does.
    if (
        job.status not in (IngestJobStatus.FAILED, IngestJobStatus.PAUSED)
        or job.stats.get("resumable") is not True
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ingest job is not resumable")
    try:
        ingestor = container.get_confluence_subtree_ingestor()
        canonical_url = ingestor.resume_url(job_id=job.id)
        base_url, space_key, page_id = await _resolve_canonical_url(canonical_url, container)
        job.active_key = _canonical_key(base_url, space_key, page_id)
        job.status = IngestJobStatus.PENDING
        job.completed_at = None
        job.error = None
        # A resumed sync must stay a sync: re-queuing it as a plain subtree
        # ingest would silently drop the tombstone step, leaving pages that
        # were deleted at the source alive in the index forever.
        kind = job.stats.get("kind")
        kind = kind if kind in ("subtree", "sync_apply") else "subtree"
        job.stats = {"phase": "queued", "resumable": False, "kind": kind, "url": canonical_url}
        await container.ingest_job_repo.update(job)
    except ConfluenceSubtreeIngestError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.category)
    except Exception:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume unavailable")
    await container.get_confluence_ingest_queue().put(
        ConfluenceIngestTask(kind=kind, job_id=job.id, url=canonical_url)
    )
    return _to_response(job)


@router.get("", response_model=list[IngestJobResponse])
async def list_recent_ingest_jobs(
    limit: int = 20,
    container: AppContainer = Depends(_container),
) -> list[IngestJobResponse]:
    """Retrieve a list of the most recent ingest jobs."""
    jobs = await container.ingest_job_repo.get_recent_jobs(limit=limit)
    return [_to_response(job) for job in jobs]


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
    # Same omitted-means-unchanged rule as the fields above: `stats` is
    # optional on the request, so an unconditional assignment wiped it to
    # None on any PATCH that did not send it — and `IngestJobResponse.stats`
    # is a required dict, so the endpoint then failed on its own response.
    if body.stats is not None:
        job.stats = body.stats

    await container.ingest_job_repo.update(job)
    return _to_response(job)
