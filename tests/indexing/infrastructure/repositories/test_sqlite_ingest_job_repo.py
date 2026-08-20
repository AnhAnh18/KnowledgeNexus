from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJob, IngestJobStatus
from knowledgenexus.indexing.infrastructure.database.engine import (
    create_engine,
    create_session_factory,
    init_database,
)
from knowledgenexus.indexing.infrastructure.repositories.sqlite_ingest_job_repo import (
    SqliteIngestJobRepository,
)


def _make_job(
    *,
    job_id: str = "job-001",
    status: IngestJobStatus = IngestJobStatus.PENDING,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error: str | None = None,
    stats: dict | None = None,
    active_key: str | None = None,
) -> IngestJob:
    return IngestJob(
        id=job_id,
        source_type=SourceType.CONFLUENCE,
        status=status,
        started_at=started_at or datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC),
        completed_at=completed_at,
        error=error,
        stats=stats or {},
        active_key=active_key,
    )



@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_database(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get_by_id(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    job = _make_job(stats={"chunks": 10})

    await repo.create(job)

    loaded = await repo.get_by_id("job-001")
    assert loaded is not None
    assert loaded.id == "job-001"
    assert loaded.source_type == SourceType.CONFLUENCE
    assert loaded.status == IngestJobStatus.PENDING
    assert loaded.started_at.replace(tzinfo=None) == datetime(2026, 7, 15, 10, 0, 0)
    assert loaded.completed_at is None
    assert loaded.error is None
    assert loaded.stats == {"chunks": 10}



@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found(session_factory):
    repo = SqliteIngestJobRepository(session_factory)

    loaded = await repo.get_by_id("nonexistent")
    assert loaded is None


@pytest.mark.asyncio
async def test_update_existing_job(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    job = _make_job()
    await repo.create(job)

    updated = _make_job(
        job_id="job-001",
        status=IngestJobStatus.COMPLETED,
        completed_at=datetime(2026, 7, 15, 11, 0, 0, tzinfo=UTC),
        stats={"chunks": 50, "documents": 5},
    )
    await repo.update(updated)

    loaded = await repo.get_by_id("job-001")
    assert loaded is not None
    assert loaded.status == IngestJobStatus.COMPLETED
    assert loaded.completed_at.replace(tzinfo=None) == datetime(2026, 7, 15, 11, 0, 0)
    assert loaded.stats == {"chunks": 50, "documents": 5}



@pytest.mark.asyncio
async def test_update_inserts_when_not_found(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    job = _make_job(job_id="job-002", status=IngestJobStatus.RUNNING)

    await repo.update(job)

    loaded = await repo.get_by_id("job-002")
    assert loaded is not None
    assert loaded.status == IngestJobStatus.RUNNING


@pytest.mark.asyncio
async def test_update_failed_job_with_error(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    job = _make_job()
    await repo.create(job)

    failed = _make_job(
        job_id="job-001",
        status=IngestJobStatus.FAILED,
        completed_at=datetime(2026, 7, 15, 10, 5, 0, tzinfo=UTC),
        error="Connection timeout",
    )
    await repo.update(failed)

    loaded = await repo.get_by_id("job-001")
    assert loaded is not None
    assert loaded.status == IngestJobStatus.FAILED
    assert loaded.error == "Connection timeout"
    assert loaded.completed_at.replace(tzinfo=None) == datetime(2026, 7, 15, 10, 5, 0)



@pytest.mark.asyncio
async def test_update_preserves_started_at(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    original_started = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)
    job = _make_job(started_at=original_started)
    await repo.create(job)

    updated = _make_job(
        job_id="job-001",
        status=IngestJobStatus.COMPLETED,
        completed_at=datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC),
    )
    await repo.update(updated)

    loaded = await repo.get_by_id("job-001")
    assert loaded is not None
    assert loaded.started_at.replace(tzinfo=None) == original_started.replace(tzinfo=None)



@pytest.mark.asyncio
async def test_create_multiple_jobs_distinct(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    job1 = _make_job(job_id="job-a", status=IngestJobStatus.PENDING)
    job2 = _make_job(job_id="job-b", status=IngestJobStatus.RUNNING)
    await repo.create(job1)
    await repo.create(job2)

    loaded_a = await repo.get_by_id("job-a")
    loaded_b = await repo.get_by_id("job-b")
    assert loaded_a is not None
    assert loaded_b is not None
    assert loaded_a.id == "job-a"
    assert loaded_b.id == "job-b"
    assert loaded_a.status == IngestJobStatus.PENDING
    assert loaded_b.status == IngestJobStatus.RUNNING


@pytest.mark.asyncio
async def test_create_or_get_active_is_deduplicated_by_durable_key(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    key = "a" * 64
    first, created_first = await repo.create_or_get_active(
        _make_job(job_id="job-a", stats={"phase": "resolving_url"}, active_key=key)
    )
    second, created_second = await repo.create_or_get_active(
        _make_job(job_id="job-b", stats={"phase": "resolving_url"}, active_key=key)
    )

    assert created_first is True
    assert first.id == "job-a"
    assert created_second is False
    assert second.id == "job-a"


@pytest.mark.asyncio
async def test_terminal_update_releases_active_key(session_factory):
    repo = SqliteIngestJobRepository(session_factory)
    key = "b" * 64
    job, _ = await repo.create_or_get_active(_make_job(job_id="job-a", active_key=key))
    job.status = IngestJobStatus.FAILED
    job.active_key = None
    await repo.update(job)

    next_job, created = await repo.create_or_get_active(_make_job(job_id="job-b", active_key=key))
    assert created is True
    assert next_job.id == "job-b"


@pytest.mark.asyncio
async def test_get_recent_jobs(session_factory):
    repo = SqliteIngestJobRepository(session_factory)

    # Create 3 jobs with different start times
    job1 = _make_job(job_id="job-1", started_at=datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC))
    job2 = _make_job(job_id="job-2", started_at=datetime(2026, 7, 15, 10, 10, 0, tzinfo=UTC))
    job3 = _make_job(job_id="job-3", started_at=datetime(2026, 7, 15, 10, 20, 0, tzinfo=UTC))

    await repo.create(job1)
    await repo.create(job2)
    await repo.create(job3)

    # Fetch with limit = 2
    recent = await repo.get_recent_jobs(limit=2)
    assert len(recent) == 2
    assert recent[0].id == "job-3"  # Newest first
    assert recent[1].id == "job-2"

    # Fetch all
    all_jobs = await repo.get_recent_jobs(limit=10)
    assert len(all_jobs) == 3
    assert all_jobs[0].id == "job-3"
    assert all_jobs[1].id == "job-2"
    assert all_jobs[2].id == "job-1"
