from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class RetrievalSearchPort(ABC):

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        ...
