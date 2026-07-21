from __future__ import annotations

from abc import ABC, abstractmethod

from knowledgenexus.retrieval.domain.models.retrieve_result import RetrievedChunk


class ChatRetrievalPort(ABC):

    @abstractmethod
    async def retrieve(self, query: str, top_k: int, score_threshold: float) -> list[RetrievedChunk]:
        ...
