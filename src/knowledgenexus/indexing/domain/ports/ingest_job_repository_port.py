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
