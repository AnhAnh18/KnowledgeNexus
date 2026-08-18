from __future__ import annotations

from typing import Any

from knowledgenexus.indexing.domain.ports.vector_store_port import VectorStorePort
from knowledgenexus.indexing.domain.value_objects.embedding_vector import SparseVector
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk
from knowledgenexus.retrieval.domain.ports.retrieval_search_port import RetrievalSearchPort



class IndexingSearchAdapter(RetrievalSearchPort):

    def __init__(self, vector_store: VectorStorePort) -> None:
        self._vector_store = vector_store

    async def search(
        self,
        dense_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
        sparse_vector: SparseVector | None = None,
    ) -> list[ScoredChunk]:
        return await self._vector_store.search(dense_vector, top_k, filters, sparse_vector)

    async def delete_by_document_id(self, document_id: str) -> int:
        return await self._vector_store.delete_by_document_id(document_id)
