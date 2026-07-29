from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from knowledgenexus.indexing.domain.value_objects.embedding_vector import SparseVector
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class RetrievalSearchPort(ABC):

    @abstractmethod
    async def search(
        self,
        dense_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
        sparse_vector: SparseVector | None = None,
    ) -> list[ScoredChunk]:
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> int:
        ...
