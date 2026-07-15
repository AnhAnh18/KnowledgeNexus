from abc import ABC, abstractmethod
from typing import Any

from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class VectorStorePort(ABC):
    @abstractmethod
    async def upsert_slim(self, chunks: list[Chunk]) -> None:
        """Upsert vectors with slim payload (filter fields only)."""
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        """Semantic search; returns chunk refs + scores (may be partial hydrate from repo)."""
        ...

    @abstractmethod
    async def delete_by_source_id(self, source_type: str, source_id: str) -> int:
        """Delete all vectors for a source. Returns count deleted."""
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> int:
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        ...
