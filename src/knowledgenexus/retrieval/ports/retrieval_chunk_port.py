from __future__ import annotations

from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class RetrievalChunkPort(ABC):

    @abstractmethod
    async def hydrate(self, slim_results: list[ScoredChunk]) -> list[ScoredChunk]:
        ...

    @abstractmethod
    async def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> int:
        ...
