from __future__ import annotations

import time

from knowledgenexus.chat.domain.models.chat_request import ChatRequest
from knowledgenexus.chat.domain.models.chat_result import ChatAnswer, ChatResult
from knowledgenexus.chat.infrastructure.prompt_builder import build_prompt
from knowledgenexus.chat.ports.llm_port import LLMPort
from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort


class RagChatUseCase:

    def __init__(self, retrieval_port: ChatRetrievalPort, llm: LLMPort) -> None:
        self._retrieval = retrieval_port
        self._llm = llm

    async def execute(self, request: ChatRequest) -> ChatResult:
        if not request.question or not request.question.strip():
            raise ValueError("Question must not be empty")

        start = time.monotonic()

        chunks = await self._retrieval.retrieve(
            query=request.question,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
        )

        prompt = build_prompt(request.question, chunks)
        answer_text, model = await self._llm.generate(prompt)

        latency_ms = int((time.monotonic() - start) * 1000)
        citations = [c.citation for c in chunks]

        return ChatResult(
            question=request.question,
            answer=ChatAnswer(text=answer_text, model=model, citations=citations),
            retrieved_count=len(chunks),
            latency_ms=latency_ms,
        )
