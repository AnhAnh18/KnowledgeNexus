"""Regression guards for the Confluence ingest queue.

A branch cut before the queue landed was merged on top of it, silently
reverting `ingest_job.py` and `container.py` to their pre-queue shape while
`app.py` kept importing `CONFLUENCE_INGEST_WORKER_COUNT` and
`confluence_ingest_worker` — the API then failed at startup with an
ImportError.  Nothing caught it: the other API tests drive the app through
`ASGITransport`, which never runs the lifespan, so the imports inside
`lifespan()` were never executed under test.

`test_app_lifespan_starts_ingest_workers` closes that hole by running the
real lifespan.  The remaining tests pin the behaviour the queue exists for:
submissions are enqueued rather than run inline, and a worker drains them one
at a time in arrival order.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.shared.di.container import AppContainer

SUBTREE_URL = "https://confluence.example.test/spaces/ENG/pages/123"


def _make_container() -> AppContainer:
    ingest_job_repo = AsyncMock()
    ingest_job_repo.get_by_id.return_value = None

    engine = MagicMock()
    conn = AsyncMock()
    conn.exec_driver_sql = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn
    engine.connect.return_value.__aexit__.return_value = None

    vector_store = AsyncMock()
    vector_store.health_check.return_value = True

    settings = MagicMock(
        storage_mode=MagicMock(value="hybrid"),
        qdrant_url="http://localhost:6333",
    )

    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=MagicMock(),
        chunk_repo=MagicMock(),
        document_repo=MagicMock(),
        ingest_job_repo=ingest_job_repo,
        vector_store=vector_store,
        chunk_storage=MagicMock(),
    )
    # These tests are about queueing, not configuration: let the ingest
    # preflight pass so it does not reject every submission with 503.
    container.confluence_ingest_config_problems = lambda: []
    return container


@pytest.fixture
def container():
    return _make_container()


@pytest.fixture
def ingest_module(monkeypatch, container):
    import importlib

    module = importlib.import_module("knowledgenexus.presentation.api.v1.ingest_job")
    monkeypatch.setattr(module, "get_container", lambda: container)
    return module


@pytest.fixture
async def api_client(ingest_module):
    import importlib

    app = importlib.import_module("knowledgenexus.presentation.api.app").app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_app_lifespan_starts_ingest_workers(monkeypatch, container, ingest_module):
    """The lifespan must be able to import and start the queue workers.

    This is the test that would have caught the regression: it executes the
    deferred imports inside `lifespan()`, so removing either
    `CONFLUENCE_INGEST_WORKER_COUNT` or `confluence_ingest_worker` from
    `ingest_job.py` fails here with ImportError instead of only at runtime.
    """
    import importlib

    container_module = importlib.import_module("knowledgenexus.shared.di.container")

    async def fake_init_container(settings):
        return container

    async def fake_shutdown_container():
        return None

    monkeypatch.setattr(container_module, "init_container", fake_init_container)
    monkeypatch.setattr(container_module, "shutdown_container", fake_shutdown_container)

    processed = asyncio.Event()

    async def fake_run(job_id, url, run_container):
        processed.set()

    monkeypatch.setattr(ingest_module, "_run_confluence_subtree_ingest_job", fake_run)

    app = importlib.import_module("knowledgenexus.presentation.api.app").app

    def running_workers() -> list[asyncio.Task]:
        return [
            task
            for task in asyncio.all_tasks()
            if getattr(task.get_coro(), "__qualname__", "") == "confluence_ingest_worker"
        ]

    # Entering the context runs the deferred imports inside `lifespan()`; the
    # real workers start, so a queued task actually gets picked up.
    async with app.router.lifespan_context(app):
        assert len(running_workers()) == ingest_module.CONFLUENCE_INGEST_WORKER_COUNT
        await container.get_confluence_ingest_queue().put(
            ingest_module.ConfluenceIngestTask(
                kind="subtree", job_id="job-lifespan", url=SUBTREE_URL
            )
        )
        await asyncio.wait_for(processed.wait(), timeout=5)

    # Workers must not outlive the app.
    assert running_workers() == []


async def test_confluence_subtree_submission_is_queued_not_run_inline(
    monkeypatch, api_client, container, ingest_module
):
    """Submissions go on the queue; they must not start work inside the request."""
    ran: list[str] = []

    async def fake_run(job_id, url, run_container):
        ran.append(job_id)

    monkeypatch.setattr(ingest_module, "_run_confluence_subtree_ingest_job", fake_run)

    async def create_or_get_active(job):
        return job, True

    container.ingest_job_repo.create_or_get_active = create_or_get_active

    first = await api_client.post(
        "/api/v1/ingest-jobs/confluence-subtrees", json={"url": SUBTREE_URL}
    )
    second = await api_client.post(
        "/api/v1/ingest-jobs/confluence-subtrees", json={"url": SUBTREE_URL + "4"}
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["status"] == "pending"
    assert first.json()["stats"]["phase"] == "queued"

    # Both submissions are waiting in the queue, and neither ran during the request.
    assert container.get_confluence_ingest_queue().qsize() == 2
    assert ran == []


async def test_submission_is_refused_when_confluence_is_not_configured(api_client, container):
    """Refuse up front, naming the setting, instead of queueing a doomed job.

    Before the preflight the job was accepted and only failed once a worker
    reached it, reporting a bare "configuration" that named nothing.
    """
    container.confluence_ingest_config_problems = lambda: ["CONFLUENCE_PAT is not set"]

    response = await api_client.post(
        "/api/v1/ingest-jobs/confluence-subtrees", json={"url": SUBTREE_URL}
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "CONFLUENCE_PAT" in detail
    assert ".env" in detail
    # No job was created and nothing was queued.
    container.ingest_job_repo.create_or_get_active.assert_not_called()
    assert container.get_confluence_ingest_queue().qsize() == 0


async def test_resume_is_refused_when_confluence_is_not_configured(api_client, container):
    container.confluence_ingest_config_problems = lambda: ["CONFLUENCE_BASE_URL is not set"]

    response = await api_client.post("/api/v1/ingest-jobs/job-x/resume")

    assert response.status_code == 503
    assert "CONFLUENCE_BASE_URL" in response.json()["detail"]


async def test_confluence_page_submission_is_queued(api_client, container):
    """The single-page endpoint shares the same queue."""
    response = await api_client.post(
        "/api/v1/ingest-jobs/confluence-pages",
        json={"url": "https://confluence.example.test/pages/viewpage.action?pageId=123"},
    )

    assert response.status_code == 202
    queue = container.get_confluence_ingest_queue()
    assert queue.qsize() == 1
    assert queue.get_nowait().kind == "page"


async def test_worker_drains_queue_one_job_at_a_time(monkeypatch, container, ingest_module):
    """Queued jobs run in arrival order and never overlap."""
    events: list[tuple[str, str]] = []

    async def fake_run(job_id, url, run_container):
        events.append(("start", job_id))
        await asyncio.sleep(0.01)
        events.append(("end", job_id))

    monkeypatch.setattr(ingest_module, "_run_confluence_subtree_ingest_job", fake_run)

    queue = container.get_confluence_ingest_queue()
    for job_id in ("job-a", "job-b", "job-c"):
        await queue.put(
            ingest_module.ConfluenceIngestTask(kind="subtree", job_id=job_id, url=SUBTREE_URL)
        )

    worker = asyncio.create_task(ingest_module.confluence_ingest_worker(container))
    await asyncio.wait_for(queue.join(), timeout=5)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert events == [
        ("start", "job-a"), ("end", "job-a"),
        ("start", "job-b"), ("end", "job-b"),
        ("start", "job-c"), ("end", "job-c"),
    ]


async def test_worker_survives_a_failing_job(monkeypatch, container, ingest_module):
    """One job blowing up must not kill the worker and stall every later job."""
    ran: list[str] = []

    async def fake_run(job_id, url, run_container):
        ran.append(job_id)
        if job_id == "job-boom":
            raise RuntimeError("boom")

    monkeypatch.setattr(ingest_module, "_run_confluence_subtree_ingest_job", fake_run)

    queue = container.get_confluence_ingest_queue()
    for job_id in ("job-boom", "job-after"):
        await queue.put(
            ingest_module.ConfluenceIngestTask(kind="subtree", job_id=job_id, url=SUBTREE_URL)
        )

    worker = asyncio.create_task(ingest_module.confluence_ingest_worker(container))
    await asyncio.wait_for(queue.join(), timeout=5)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert ran == ["job-boom", "job-after"]


async def test_resume_re_enqueues_failed_job(monkeypatch, api_client, container, ingest_module):
    """Resuming a checkpointed job puts it back on the queue as PENDING."""
    job = IngestJob(
        id="job-resume",
        source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.FAILED,
        started_at=datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 15, 10, 5, 0, tzinfo=UTC),
        error="foundation",
        stats={"phase": "failed", "resumable": True},
    )
    container.ingest_job_repo.get_by_id.return_value = job
    container.confluence_subtree_ingestor = MagicMock(resume_url=MagicMock(return_value=SUBTREE_URL))

    async def fake_resolve(url, resolve_container):
        return ("https://confluence.example.test", "ENG", "123")

    monkeypatch.setattr(ingest_module, "_resolve_canonical_url", fake_resolve)

    response = await api_client.post("/api/v1/ingest-jobs/job-resume/resume")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["error"] is None

    queue = container.get_confluence_ingest_queue()
    assert queue.qsize() == 1
    task = queue.get_nowait()
    assert task.kind == "subtree"
    assert task.job_id == "job-resume"


async def test_failure_keeps_the_phase_it_died_in(monkeypatch, container, ingest_module):
    """A failed job must say where it stopped, without needing server logs.

    `stats` used to be replaced wholesale on failure, discarding the phase and
    every counter -- so the only way to learn where a job broke was a
    traceback on whatever machine ran the server.
    """
    from knowledgenexus.indexing.domain.models.ingest_job import IngestJob

    job = IngestJob(
        id="job-fail",
        source_type=SourceType.CONFLUENCE,
        status=IngestJobStatus.RUNNING,
        started_at=datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC),
        stats={"phase": "queued", "resumable": False},
    )
    container.ingest_job_repo.get_by_id.return_value = job

    async def fake_resolve(url, resolve_container):
        return ("https://confluence.example.test", "ENG", "123")

    monkeypatch.setattr(ingest_module, "_resolve_canonical_url", fake_resolve)

    class _FailsAtDrawio:
        """Gets as far as capturing draw.io diagrams, then dies -- like the real one."""

        async def execute(self, *, job_id, canonical_url, report_progress):
            await report_progress({"phase": "inventory", "requested_pages": 12})
            await report_progress({"phase": "capture_pages", "captured_pages": 12})
            await report_progress({"phase": "capture_drawio"})
            raise ingest_module.ConfluenceSubtreeIngestError("foundation", resumable=True)

    container.get_confluence_subtree_ingestor = lambda: _FailsAtDrawio()

    await ingest_module._run_confluence_subtree_ingest_job(
        "job-fail", SUBTREE_URL, container
    )

    assert job.status is IngestJobStatus.FAILED
    assert job.error == "foundation"
    assert job.stats["phase"] == "failed"
    assert job.stats["failed_phase"] == "capture_drawio"
    # Counters earned before the failure survive too.
    assert job.stats["captured_pages"] == 12
    assert job.stats["resumable"] is True


class TestCancel:
    """Cancelling a queued job is immediate; a running job stops cooperatively."""

    def _job(self, status: IngestJobStatus, **stats) -> IngestJob:
        return IngestJob(
            id="job-cancel",
            source_type=SourceType.CONFLUENCE,
            status=status,
            started_at=datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC),
            stats=stats or {"phase": "queued", "resumable": False},
        )

    async def test_queued_job_is_cancelled_outright(self, api_client, container, ingest_module):
        job = self._job(IngestJobStatus.PENDING)
        container.ingest_job_repo.get_by_id.return_value = job

        response = await api_client.post("/api/v1/ingest-jobs/job-cancel/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert job.status is IngestJobStatus.CANCELLED
        assert job.active_key is None
        # Cancelling is not an error.
        assert job.error is None
        assert job.stats["resumable"] is False
        ingest_module._CANCEL_REQUESTED.discard("job-cancel")

    async def test_running_job_that_owns_a_workspace_is_paused_and_resumable(
        self, container, ingest_module
    ):
        """Stopping mid-crawl leaves the same half-built workspace a resumable
        failure does, so it must be resumable rather than thrown away."""
        job = self._job(IngestJobStatus.RUNNING, phase="capture_pages", captured_pages=40)

        ingest_module._mark_stopped(job)

        assert job.status is IngestJobStatus.PAUSED
        assert job.stats["resumable"] is True
        assert job.stats["failed_phase"] == "capture_pages"
        assert job.stats["captured_pages"] == 40
        assert job.error is None

    async def test_stopping_before_any_crawl_is_cancelled_not_paused(
        self, container, ingest_module
    ):
        """No workspace exists yet, so pretending it can resume would lie."""
        job = self._job(IngestJobStatus.RUNNING, phase="resolving_url")

        ingest_module._mark_stopped(job)

        assert job.status is IngestJobStatus.CANCELLED
        assert job.stats["resumable"] is False

    async def test_paused_job_can_be_resumed(
        self, monkeypatch, api_client, container, ingest_module
    ):
        job = self._job(IngestJobStatus.PAUSED, phase="paused", resumable=True)
        job.stats["resumable"] = True
        container.ingest_job_repo.get_by_id.return_value = job
        container.confluence_subtree_ingestor = MagicMock(
            resume_url=MagicMock(return_value=SUBTREE_URL)
        )

        async def fake_resolve(url, resolve_container):
            return ("https://confluence.example.test", "ENG", "123")

        monkeypatch.setattr(ingest_module, "_resolve_canonical_url", fake_resolve)

        response = await api_client.post("/api/v1/ingest-jobs/job-cancel/resume")

        assert response.status_code == 202
        assert response.json()["status"] == "pending"
        assert container.get_confluence_ingest_queue().qsize() == 1

    async def test_cancelled_job_cannot_be_resumed(self, api_client, container):
        """Nothing was crawled, so there is genuinely nothing to continue."""
        job = self._job(IngestJobStatus.CANCELLED, phase="cancelled", resumable=False)
        job.stats["resumable"] = False
        container.ingest_job_repo.get_by_id.return_value = job

        response = await api_client.post("/api/v1/ingest-jobs/job-cancel/resume")

        assert response.status_code == 409

    async def test_running_job_is_flagged_and_stays_running_until_it_yields(
        self, api_client, container, ingest_module
    ):
        job = self._job(IngestJobStatus.RUNNING, phase="capture_pages", captured_pages=40)
        container.ingest_job_repo.get_by_id.return_value = job

        response = await api_client.post("/api/v1/ingest-jobs/job-cancel/cancel")

        assert response.status_code == 200
        # A blocking crawl cannot be killed, so it is still running for now.
        assert response.json()["status"] == "running"
        assert "job-cancel" in ingest_module._CANCEL_REQUESTED
        ingest_module._CANCEL_REQUESTED.discard("job-cancel")

    async def test_progress_callback_unwinds_a_cancelled_run(self, container, ingest_module):
        job = self._job(IngestJobStatus.RUNNING, phase="capture_pages")
        ingest_module._CANCEL_REQUESTED.add("job-cancel")
        try:
            with pytest.raises(ingest_module._IngestJobCancelled):
                await ingest_module._set_progress(
                    job, container, {"phase": "process_pages"}
                )
        finally:
            ingest_module._CANCEL_REQUESTED.discard("job-cancel")

    async def test_cancelled_queued_job_is_skipped_by_the_worker(
        self, monkeypatch, container, ingest_module
    ):
        job = self._job(IngestJobStatus.CANCELLED)
        container.ingest_job_repo.get_by_id.return_value = job
        monkeypatch.setattr(
            ingest_module, "_resolve_canonical_url",
            lambda *a, **k: pytest.fail("a cancelled job must not start work"),
        )

        await ingest_module._run_confluence_subtree_ingest_job(
            "job-cancel", SUBTREE_URL, container
        )

        assert job.status is IngestJobStatus.CANCELLED

    async def test_finished_job_cannot_be_cancelled(self, api_client, container):
        job = self._job(IngestJobStatus.COMPLETED)
        container.ingest_job_repo.get_by_id.return_value = job

        response = await api_client.post("/api/v1/ingest-jobs/job-cancel/cancel")

        assert response.status_code == 409
        assert "completed" in response.json()["detail"]

    async def test_cancel_of_unknown_job_is_404(self, api_client, container):
        container.ingest_job_repo.get_by_id.return_value = None

        response = await api_client.post("/api/v1/ingest-jobs/nope/cancel")

        assert response.status_code == 404
