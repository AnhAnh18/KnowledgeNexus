"""Tests for RagChatUseCase — RAG pipeline orchestration.

Covers: happy path, empty question, no chunks, LLM error propagation, citations.
Uses mocks for retrieval port and LLM port.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from knowledgenexus.chat.application.use_cases.rag_chat import RagChatUseCase
from knowledgenexus.chat.domain.models.chat_request import ChatRequest
from knowledgenexus.chat.infrastructure.llm.agent_builder_adapter import LLMProviderError
from knowledgenexus.chat.ports.llm_port import LLMPort
from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort
from knowledgenexus.retrieval.domain.models.retrieve_result import Citation, RetrievedChunk


def _make_chunk(
    content: str = "SPen SDK is a development toolkit.",
    title: str = "SPen SDK Docs",
) -> RetrievedChunk:
    return RetrievedChunk(
        content=content,
        score=0.85,
        citation=Citation(
            chunk_id="chunk-1",
            document_id=uuid4(),
            title=title,
            url="https://example.com",
            source_type="FILE",
            source_id="README",
            chunk_index=0,
            total_chunks=1,
        ),
    )


@pytest.fixture
def mock_retrieval_port() -> ChatRetrievalPort:
    port = AsyncMock(spec=ChatRetrievalPort)
    port.retrieve = AsyncMock(return_value=[_make_chunk()])
    return port


@pytest.fixture
def mock_llm_port() -> LLMPort:
    port = AsyncMock(spec=LLMPort)
    port.generate = AsyncMock(return_value=("SPen SDK is a toolkit for pen input.", "test-model"))
    return port


@pytest.fixture
def use_case(mock_retrieval_port, mock_llm_port) -> RagChatUseCase:
    return RagChatUseCase(retrieval_port=mock_retrieval_port, llm=mock_llm_port)


class TestRagChatHappyPath:
    """Verify happy path: retrieve → build prompt → LLM generate → return result."""

    @pytest.mark.asyncio
    async def test_execute_returns_result(self, use_case, mock_retrieval_port, mock_llm_port):
        request = ChatRequest(question="What is SPen SDK?")
        result = await use_case.execute(request)

        assert result.question == "What is SPen SDK?"
        assert result.answer.text == "SPen SDK is a toolkit for pen input."
        assert result.answer.model == "test-model"
        assert result.retrieved_count == 1
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_calls_retrieval_with_params(self, use_case, mock_retrieval_port):
        request = ChatRequest(question="test", top_k=10, score_threshold=0.5)
        await use_case.execute(request)

        mock_retrieval_port.retrieve.assert_called_once_with(
            query="test", top_k=10, score_threshold=0.5
        )

    @pytest.mark.asyncio
    async def test_execute_calls_llm_with_prompt(self, use_case, mock_llm_port):
        request = ChatRequest(question="What is SPen SDK?")
        await use_case.execute(request)

        mock_llm_port.generate.assert_called_once()
        prompt = mock_llm_port.generate.call_args[0][0]
        assert "What is SPen SDK?" in prompt
        assert "SPen SDK is a development toolkit." in prompt  # chunk content

    @pytest.mark.asyncio
    async def test_execute_includes_citations(self, use_case):
        request = ChatRequest(question="test")
        result = await use_case.execute(request)

        assert len(result.answer.citations) == 1
        assert result.answer.citations[0].title == "SPen SDK Docs"


class TestRagChatEdgeCases:
    """Verify edge cases: empty question, no chunks."""

    @pytest.mark.asyncio
    async def test_empty_question_raises_value_error(self, use_case):
        request = ChatRequest(question="")
        with pytest.raises(ValueError, match="must not be empty"):
            await use_case.execute(request)

    @pytest.mark.asyncio
    async def test_whitespace_question_raises_value_error(self, use_case):
        request = ChatRequest(question="   ")
        with pytest.raises(ValueError, match="must not be empty"):
            await use_case.execute(request)

    @pytest.mark.asyncio
    async def test_no_chunks_still_calls_llm(self, use_case, mock_retrieval_port, mock_llm_port):
        mock_retrieval_port.retrieve = AsyncMock(return_value=[])
        request = ChatRequest(question="What is AI?")
        result = await use_case.execute(request)

        assert result.retrieved_count == 0
        assert len(result.answer.citations) == 0
        mock_llm_port.generate.assert_called_once()
        prompt = mock_llm_port.generate.call_args[0][0]
        assert "No relevant context found" in prompt


class TestRagChatErrorPropagation:
    """Verify LLM errors propagate correctly."""

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self, use_case, mock_llm_port):
        mock_llm_port.generate = AsyncMock(side_effect=LLMProviderError("API down"))
        request = ChatRequest(question="test")
        with pytest.raises(LLMProviderError, match="API down"):
            await use_case.execute(request)

    @pytest.mark.asyncio
    async def test_retrieval_error_propagates(self, use_case, mock_retrieval_port):
        mock_retrieval_port.retrieve = AsyncMock(side_effect=RuntimeError("Qdrant unreachable"))
        request = ChatRequest(question="test")
        with pytest.raises(RuntimeError, match="Qdrant unreachable"):
            await use_case.execute(request)


class TestRagChatDependencyInversion:
    """Verify use case depends on abstract ports, not concrete implementations."""

    def test_depends_on_llm_port(self):
        """Verify RagChatUseCase.__init__ accepts LLMPort (via type hints)."""
        from knowledgenexus.chat.ports.llm_port import LLMPort
        import inspect
        from typing import get_type_hints
        hints = get_type_hints(RagChatUseCase.__init__)
        assert hints.get("llm") is LLMPort

    def test_depends_on_retrieval_port(self):
        """Verify RagChatUseCase.__init__ accepts ChatRetrievalPort (via type hints)."""
        from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort
        import inspect
        from typing import get_type_hints
        hints = get_type_hints(RagChatUseCase.__init__)
        assert hints.get("retrieval_port") is ChatRetrievalPort
