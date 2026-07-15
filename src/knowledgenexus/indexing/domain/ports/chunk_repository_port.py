from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class ChunkRepositoryPort(ABC):
    @abstractmethod
    async def save_batch(self, chunks: list[Chunk]) -> None:
        ...

    @abstractmethod
    async def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        ...

    @abstractmethod
    async def get_by_document_id(self, document_id: str) -> list[Chunk]:
        ...

    @abstractmethod
    async def delete_by_source_id(self, source_type: str, source_id: str) -> int:
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> int:
        ...

    @abstractmethod
    async def hydrate(self, slim_results: list[ScoredChunk]) -> list[ScoredChunk]:
        """Join full chunk content + extra from DB onto slim search results."""
        ...
