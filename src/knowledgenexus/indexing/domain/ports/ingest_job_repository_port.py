from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.models.ingest_job import IngestJob


class IngestJobRepositoryPort(ABC):
    @abstractmethod
    async def create(self, job: IngestJob) -> None:
        ...

    @abstractmethod
    async def update(self, job: IngestJob) -> None:
        ...

    @abstractmethod
    async def get_by_id(self, job_id: str) -> IngestJob | None:
        ...

    @abstractmethod
    async def create_or_get_active(self, job: IngestJob) -> tuple[IngestJob, bool]:
        """Atomically create an active job, or return its existing owner."""
        ...

    @abstractmethod
    async def get_by_active_key(self, active_key: str) -> IngestJob | None:
        ...
