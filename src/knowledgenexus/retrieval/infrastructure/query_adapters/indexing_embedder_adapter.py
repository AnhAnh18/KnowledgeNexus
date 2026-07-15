from __future__ import annotations

from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort
from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector
from knowledgenexus.retrieval.domain.ports.query_embedder_port import QueryEmbedderPort


class IndexingEmbedderAdapter(QueryEmbedderPort):

    def __init__(self, embedder: EmbedderPort) -> None:
        self._embedder = embedder

    @property
    def model_name(self) -> str:
        return self._embedder.model_name

    @property
    def dimension(self) -> int:
        return self._embedder.dimension

    async def embed_query(self, query: str) -> EmbeddingVector:
        return await self._embedder.embed_query(query)
