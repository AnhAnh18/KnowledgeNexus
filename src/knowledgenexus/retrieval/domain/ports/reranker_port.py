from __future__ import annotations

from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class RerankerPort(ABC):
    """Abstract port for reranking retrieved chunks using a cross-encoder model.

    A reranker receives a list of candidate chunks (typically retrieved via
    dense/sparse hybrid search) and re-scores them using a cross-encoder
    that jointly encodes the query-document pair, producing a more accurate
    relevance score than bi-encoder similarity.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Rerank candidate chunks by relevance to the query.

        Args:
            query: The user's search query.
            candidates: Candidate chunks retrieved from the vector store.
            top_k: Number of top chunks to return after reranking.

        Returns:
            Reranked list of ScoredChunk, sorted by cross-encoder score
            (descending), truncated to ``top_k``.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release model resources."""
        ...
