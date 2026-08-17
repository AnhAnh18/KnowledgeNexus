from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledgenexus.indexing.domain.models.ingest_job import IngestJob
from knowledgenexus.indexing.domain.ports.ingest_job_repository_port import IngestJobRepositoryPort

from knowledgenexus.indexing.infrastructure.database.mappers import ingest_job_from_model, ingest_job_to_model
from knowledgenexus.indexing.infrastructure.database.models import IngestJobModel


class SqliteIngestJobRepository(IngestJobRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, job: IngestJob) -> None:
        async with self._session_factory() as session:
            session.add(ingest_job_to_model(job))
            await session.commit()

    async def update(self, job: IngestJob) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(IngestJobModel).where(IngestJobModel.id == job.id))
            model = result.scalar_one_or_none()
            if model is None:
                session.add(ingest_job_to_model(job))
            else:
                model.source_type = str(job.source_type)
                model.status = job.status.value
                model.started_at = job.started_at
                model.completed_at = job.completed_at
                model.error = job.error
                model.stats = job.stats
                model.active_key = job.active_key
            await session.commit()

    async def get_by_id(self, job_id: str) -> IngestJob | None:
        async with self._session_factory() as session:
            result = await session.execute(select(IngestJobModel).where(IngestJobModel.id == job_id))
            model = result.scalar_one_or_none()
            return ingest_job_from_model(model) if model else None

    async def create_or_get_active(self, job: IngestJob) -> tuple[IngestJob, bool]:
        if type(job.active_key) is not str or len(job.active_key) != 64:
            raise ValueError("active job requires a SHA-256 active key")
        try:
            async with self._session_factory() as session:
                session.add(ingest_job_to_model(job))
                await session.commit()
            return job, True
        except IntegrityError:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(IngestJobModel).where(IngestJobModel.active_key == job.active_key)
                )
                model = result.scalar_one_or_none()
                if model is None:
                    raise
                return ingest_job_from_model(model), False

    async def get_by_active_key(self, active_key: str) -> IngestJob | None:
        if type(active_key) is not str or len(active_key) != 64:
            raise ValueError("active key is invalid")
        async with self._session_factory() as session:
            result = await session.execute(
                select(IngestJobModel).where(IngestJobModel.active_key == active_key)
            )
            model = result.scalar_one_or_none()
            return ingest_job_from_model(model) if model else None
