from __future__ import annotations

from typing import Any

from knowledgenexus.indexing.domain.ports.vector_store_port import VectorStorePort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk
from knowledgenexus.retrieval.domain.ports.retrieval_search_port import RetrievalSearchPort



class IndexingSearchAdapter(RetrievalSearchPort):

    def __init__(self, vector_store: VectorStorePort) -> None:
        self._vector_store = vector_store

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        return await self._vector_store.search(query_vector, top_k, filters)
