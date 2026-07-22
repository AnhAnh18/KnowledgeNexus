"""Tests for RetrievalAdapter — bridges ChatRetrievalPort to RetrieveChunksUseCase.

Covers: retrieve delegates to use case, passes params correctly, returns results.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from knowledgenexus.chat.infrastructure.retrieval_adapter import RetrievalAdapter
from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase
from knowledgenexus.retrieval.domain.models.retrieve_request import RetrieveRequest
from knowledgenexus.retrieval.domain.models.retrieve_result import (
    Citation,
    RetrieveResult,
    RetrievedChunk,
)


def _make_chunk(content: str = "test content") -> RetrievedChunk:
    return RetrievedChunk(
        content=content,
        score=0.9,
        citation=Citation(
            chunk_id="chunk-1",
            document_id=uuid4(),
            title="Test",
            url="https://example.com",
            source_type="FILE",
            source_id="README",
            chunk_index=0,
            total_chunks=1,
        ),
    )


@pytest.fixture
def mock_use_case() -> RetrieveChunksUseCase:
    use_case = AsyncMock(spec=RetrieveChunksUseCase)
    result = RetrieveResult(query="test", total=1, results=[_make_chunk()])
    use_case.execute = AsyncMock(return_value=result)
    return use_case


@pytest.fixture
def adapter(mock_use_case) -> RetrievalAdapter:
    return RetrievalAdapter(mock_use_case)


class TestRetrievalAdapterRetrieve:
    """Verify retrieve() delegates to use case and returns chunks."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_chunks(self, adapter, mock_use_case):
        chunks = await adapter.retrieve(query="SPen SDK", top_k=5, score_threshold=0.3)

        assert len(chunks) == 1
        assert chunks[0].content == "test content"
        assert chunks[0].score == 0.9
        mock_use_case.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_passes_correct_request(self, adapter, mock_use_case):
        await adapter.retrieve(query="BGE-M3", top_k=10, score_threshold=0.5)

        call_args = mock_use_case.execute.call_args[0][0]
        assert isinstance(call_args, RetrieveRequest)
        assert call_args.query == "BGE-M3"
        assert call_args.top_k == 10
        assert call_args.score_threshold == 0.5

    @pytest.mark.asyncio
    async def test_retrieve_empty_results(self, adapter, mock_use_case):
        mock_use_case.execute = AsyncMock(
            return_value=RetrieveResult(query="test", total=0, results=[])
        )
        chunks = await adapter.retrieve(query="nonexistent", top_k=5, score_threshold=0.0)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_retrieve_use_case_error_propagates(self, adapter, mock_use_case):
        mock_use_case.execute = AsyncMock(side_effect=RuntimeError("Qdrant connection failed"))

        with pytest.raises(RuntimeError, match="Qdrant connection failed"):
            await adapter.retrieve(query="test", top_k=5, score_threshold=0.0)

    @pytest.mark.asyncio
    async def test_retrieve_default_params(self, adapter, mock_use_case):
        await adapter.retrieve(query="test", top_k=5, score_threshold=0.0)

        call_args = mock_use_case.execute.call_args[0][0]
        assert call_args.top_k == 5
        assert call_args.score_threshold == 0.0


class TestRetrievalAdapterIsChatRetrievalPort:
    """Verify RetrievalAdapter implements ChatRetrievalPort."""

    def test_is_chat_retrieval_port_subclass(self):
        from knowledgenexus.chat.ports.retrieval_port import ChatRetrievalPort
        assert issubclass(RetrievalAdapter, ChatRetrievalPort)
