from __future__ import annotations

from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort
from knowledgenexus.retrieval.domain.models.retrieve_request import RetrieveRequest
from knowledgenexus.retrieval.domain.models.retrieve_result import RetrievedChunk
from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase


class RetrievalAdapter(ChatRetrievalPort):

    def __init__(self, retrieve_use_case: RetrieveChunksUseCase) -> None:
        self._use_case = retrieve_use_case

    async def retrieve(self, query: str, top_k: int, score_threshold: float) -> list[RetrievedChunk]:
        request = RetrieveRequest(query=query, top_k=top_k, score_threshold=score_threshold)
        result = await self._use_case.execute(request)
        return result.results
