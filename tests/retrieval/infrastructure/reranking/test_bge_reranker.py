"""Unit tests for BgeReranker.

These tests use mocking to avoid loading the real bge-reranker-v2-m3 model
(which is ~2GB). Integration tests that exercise the real model should be
marked with ``@pytest.mark.integration`` and run separately.
"""

from __future__ import annotations

import sys
import types
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_flag_reranker_module():
    """Inject a fake FlagEmbedding module so patch doesn't need the real package."""
    fake_module = types.ModuleType("FlagEmbedding")
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance
    fake_module.FlagReranker = mock_cls

    original = sys.modules.get("FlagEmbedding")
    sys.modules["FlagEmbedding"] = fake_module

    try:
        yield mock_instance
    finally:
        if original is not None:
            sys.modules["FlagEmbedding"] = original
        else:
            sys.modules.pop("FlagEmbedding", None)


@pytest.fixture
def reranker(mock_flag_reranker_module):
    """Create a BgeReranker with a mocked model."""
    from knowledgenexus.retrieval.infrastructure.reranking.bge_reranker import BgeReranker

    return BgeReranker(device="cpu")


def _make_chunk(chunk_id: str, content: str) -> Chunk:
    """Create a minimal Chunk for testing."""
    from uuid import uuid4

    core = CoreChunkMetadata(
        document_id=uuid4(),
        source_type=SourceType.FILE,
        source_id="test-source",
        title="Test",
        url=None,
        chunk_index=0,
        total_chunks=1,
        indexed_at=None,
        embedding_model="BAAI/bge-m3",
    )
    return Chunk(
        id=chunk_id,
        payload=ChunkPayload(core=core, content=content, extra={}),
    )


def _make_scored_chunk(chunk_id: str, content: str, score: float = 0.5) -> ScoredChunk:
    """Create a ScoredChunk for testing."""
    return ScoredChunk(chunk=_make_chunk(chunk_id, content), score=score)


# ---------------------------------------------------------------------------
# Rerank tests
# ---------------------------------------------------------------------------

class TestRerank:
    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(self, reranker, mock_flag_reranker_module):
        """Reranker should return candidates sorted by cross-encoder score descending."""
        # Mock compute_score to return scores in different order than input
        mock_flag_reranker_module.compute_score.return_value = [0.9, 0.3, 0.7]

        candidates = [
            _make_scored_chunk("c1", "doc one", score=0.5),
            _make_scored_chunk("c2", "doc two", score=0.8),
            _make_scored_chunk("c3", "doc three", score=0.2),
        ]

        result = await reranker.rerank("test query", candidates, top_k=3)

        assert len(result) == 3
        # Should be sorted by reranker score descending
        assert result[0].chunk.id == "c1"  # score 0.9
        assert result[1].chunk.id == "c3"  # score 0.7
        assert result[2].chunk.id == "c2"  # score 0.3
        # Scores should be updated to reranker scores
        assert result[0].score == 0.9
        assert result[1].score == 0.7
        assert result[2].score == 0.3

    @pytest.mark.asyncio
    async def test_rerank_truncates_to_top_k(self, reranker, mock_flag_reranker_module):
        """Reranker should truncate results to top_k."""
        mock_flag_reranker_module.compute_score.return_value = [0.9, 0.3, 0.7, 0.1, 0.5]

        candidates = [
            _make_scored_chunk(f"c{i}", f"doc {i}", score=0.5)
            for i in range(5)
        ]

        result = await reranker.rerank("test query", candidates, top_k=2)

        assert len(result) == 2
        assert result[0].score == 0.9
        assert result[1].score == 0.7

    @pytest.mark.asyncio
    async def test_rerank_empty_candidates_returns_empty(self, reranker, mock_flag_reranker_module):
        """Reranker should return empty list for empty candidates."""
        result = await reranker.rerank("test query", [], top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_empty_query_raises(self, reranker, mock_flag_reranker_module):
        """Reranker should raise ValueError for empty query."""
        candidates = [_make_scored_chunk("c1", "doc one")]
        with pytest.raises(ValueError, match="empty"):
            await reranker.rerank("", candidates, top_k=1)

    @pytest.mark.asyncio
    async def test_rerank_whitespace_query_raises(self, reranker, mock_flag_reranker_module):
        """Reranker should raise ValueError for whitespace-only query."""
        candidates = [_make_scored_chunk("c1", "doc one")]
        with pytest.raises(ValueError, match="empty"):
            await reranker.rerank("   ", candidates, top_k=1)

    @pytest.mark.asyncio
    async def test_rerank_passes_query_document_pairs(self, reranker, mock_flag_reranker_module):
        """Reranker should pass [query, content] pairs to compute_score."""
        mock_flag_reranker_module.compute_score.return_value = [0.5]

        candidates = [_make_scored_chunk("c1", "some document text")]
        await reranker.rerank("my query", candidates, top_k=1)

        call_args = mock_flag_reranker_module.compute_score.call_args
        pairs = call_args[0][0]
        assert pairs == [["my query", "some document text"]]

    @pytest.mark.asyncio
    async def test_rerank_single_float_result(self, reranker, mock_flag_reranker_module):
        """Reranker should handle single float return from compute_score."""
        mock_flag_reranker_module.compute_score.return_value = 0.85

        candidates = [_make_scored_chunk("c1", "doc one")]
        result = await reranker.rerank("test query", candidates, top_k=1)

        assert len(result) == 1
        assert result[0].score == 0.85


# ---------------------------------------------------------------------------
# from_settings tests
# ---------------------------------------------------------------------------

class TestFromSettings:
    def test_from_settings_disabled_returns_none(self, mock_flag_reranker_module):
        """from_settings should return None when reranker_enabled=False."""
        from knowledgenexus.retrieval.infrastructure.reranking.bge_reranker import BgeReranker

        settings = MagicMock()
        settings.reranker_enabled = False

        result = BgeReranker.from_settings(settings)
        assert result is None

    def test_from_settings_enabled_creates_reranker(self, mock_flag_reranker_module):
        """from_settings should create a BgeReranker when enabled."""
        from knowledgenexus.retrieval.infrastructure.reranking.bge_reranker import BgeReranker

        settings = MagicMock()
        settings.reranker_enabled = True
        settings.reranker_model = "BAAI/bge-reranker-v2-m3"
        settings.reranker_model_path = None
        settings.reranker_device = "cpu"
        settings.reranker_batch_size = 16

        result = BgeReranker.from_settings(settings)
        assert result is not None
        assert isinstance(result, BgeReranker)
