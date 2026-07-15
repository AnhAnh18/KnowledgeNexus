from sqlalchemy import select
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
            await session.commit()

    async def get_by_id(self, job_id: str) -> IngestJob | None:
        async with self._session_factory() as session:
            result = await session.execute(select(IngestJobModel).where(IngestJobModel.id == job_id))
            model = result.scalar_one_or_none()
            return ingest_job_from_model(model) if model else None
