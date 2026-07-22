from __future__ import annotations

import logging
import time

from knowledgenexus.chat.domain.models.chat_request import ChatRequest
from knowledgenexus.chat.domain.models.chat_result import ChatAnswer, ChatResult
from knowledgenexus.chat.infrastructure.llm.agent_builder_adapter import LLMProviderError
from knowledgenexus.chat.infrastructure.prompt_builder import build_prompt
from knowledgenexus.chat.ports.llm_port import LLMPort
from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort

logger = logging.getLogger(__name__)


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
        citations = [c.citation for c in chunks]

        try:
            answer_text, model = await self._llm.generate(prompt)
        except LLMProviderError as e:
            logger.warning("LLM unavailable, returning retrieved chunks as fallback: %s", e)
            answer_text = self._build_fallback_text(chunks)
            model = "fallback:retrieval-only"

        latency_ms = int((time.monotonic() - start) * 1000)

        return ChatResult(
            question=request.question,
            answer=ChatAnswer(text=answer_text, model=model, citations=citations),
            retrieved_count=len(chunks),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _build_fallback_text(chunks: list) -> str:
        """Build a fallback response from retrieved chunks when LLM is unavailable."""
        if not chunks:
            return (
                "The AI assistant is currently unavailable and no relevant documents "
                "were found in the knowledge base. Please try again later."
            )

        parts = [
            "The AI assistant is currently unavailable. "
            "Here are the most relevant documents found in the knowledge base:\n"
        ]
        for i, chunk in enumerate(chunks, 1):
            title = chunk.citation.title
            parts.append(f"\n--- [{i}] {title} ---\n{chunk.content}")

        return "\n".join(parts)
