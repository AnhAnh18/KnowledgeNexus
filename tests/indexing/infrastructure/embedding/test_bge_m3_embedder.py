"""Unit tests for BgeM3Embedder.

These tests use mocking to avoid loading the real bge-m3 model (which is
~2GB). Integration tests that exercise the real model should be marked
with ``@pytest.mark.integration`` and run separately.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_flag_model():
    """Inject a fake FlagEmbedding module so patch doesn't need the real package."""
    # Create a fake module with BGEM3FlagModel as a MagicMock
    fake_module = types.ModuleType("FlagEmbedding")
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance
    fake_module.BGEM3FlagModel = mock_cls

    # Inject into sys.modules so the lazy import in BgeM3Embedder finds it
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
def embedder(mock_flag_model):
    """Create a BgeM3Embedder with a mocked model."""
    from knowledgenexus.indexing.infrastructure.embedding.bge_m3_embedder import BgeM3Embedder

    return BgeM3Embedder(device="cpu")


def _make_encode_output(vectors: list[list[float]]) -> dict:
    """Simulate the dict returned by BGEM3FlagModel.encode()."""
    return {"dense_vecs": vectors}


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

class TestBgeM3EmbedderProperties:
    def test_model_name(self, embedder):
        assert embedder.model_name == "BAAI/bge-m3"

    def test_dimension(self, embedder):
        assert embedder.dimension == 1024


# ---------------------------------------------------------------------------
# embed() tests (document embedding — verbatim, no prefix)
# ---------------------------------------------------------------------------

class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_single_text(self, embedder, mock_flag_model):
        fake_vector = [0.1] * 1024
        mock_flag_model.encode.return_value = _make_encode_output([fake_vector])

        result = await embedder.embed(["This is a document chunk."])

        assert len(result) == 1
        assert isinstance(result[0], EmbeddingVector)
        assert len(result[0].values) == 1024
        assert result[0].model_name == "BAAI/bge-m3"
        assert result[0].dimension == 1024

    @pytest.mark.asyncio
    async def test_embed_multiple_texts(self, embedder, mock_flag_model):
        # Use distinct vectors so they differ even after L2 normalization
        v1 = [1.0] + [0.0] * 1023
        v2 = [0.0, 1.0] + [0.0] * 1022
        v3 = [0.0, 0.0, 1.0] + [0.0] * 1021
        mock_flag_model.encode.return_value = _make_encode_output([v1, v2, v3])

        result = await embedder.embed(["text1", "text2", "text3"])

        assert len(result) == 3
        assert result[0].values != result[1].values
        assert result[1].values != result[2].values


    @pytest.mark.asyncio
    async def test_embed_empty_list_returns_empty(self, embedder):
        result = await embedder.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_does_not_add_query_prefix(self, embedder, mock_flag_model):
        """C3 contract: embed() must embed text verbatim, no prefix."""
        mock_flag_model.encode.return_value = _make_encode_output([[0.0] * 1024])

        await embedder.embed(["Some document text"])

        # Verify the text passed to model.encode is verbatim (no prefix)
        call_args = mock_flag_model.encode.call_args
        texts_passed = call_args[0][0] if call_args[0] else call_args[1].get("corpus", [])
        assert texts_passed == ["Some document text"]
        assert not texts_passed[0].startswith("Represent this sentence")


# ---------------------------------------------------------------------------
# embed_query() tests (query embedding — with prefix)
# ---------------------------------------------------------------------------

class TestEmbedQuery:
    @pytest.mark.asyncio
    async def test_embed_query_returns_vector(self, embedder, mock_flag_model):
        fake_vector = [0.5] * 1024
        mock_flag_model.encode.return_value = _make_encode_output([fake_vector])

        result = await embedder.embed_query("how to configure qdrant")

        assert isinstance(result, EmbeddingVector)
        assert len(result.values) == 1024
        assert result.model_name == "BAAI/bge-m3"
        assert result.dimension == 1024

    @pytest.mark.asyncio
    async def test_embed_query_adds_prefix(self, embedder, mock_flag_model):
        """embed_query must add the bge-m3 query instruction prefix."""
        mock_flag_model.encode.return_value = _make_encode_output([[0.0] * 1024])

        await embedder.embed_query("what is objectmanager")

        call_args = mock_flag_model.encode.call_args
        texts_passed = call_args[0][0]
        assert len(texts_passed) == 1
        assert texts_passed[0].startswith("Represent this sentence for searching relevant passages: ")
        assert "what is objectmanager" in texts_passed[0]

    @pytest.mark.asyncio
    async def test_embed_query_empty_raises(self, embedder):
        with pytest.raises(ValueError, match="empty"):
            await embedder.embed_query("")

    @pytest.mark.asyncio
    async def test_embed_query_whitespace_raises(self, embedder):
        with pytest.raises(ValueError, match="empty"):
            await embedder.embed_query("   ")


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalization:
    @pytest.mark.asyncio
    async def test_vectors_are_l2_normalized(self, embedder, mock_flag_model):
        """Output vectors should be L2-normalized for cosine search in Qdrant."""
        # Unnormalized vector: norm = sqrt(0.5^2 * 1024) = sqrt(256) = 16
        raw = [0.5] * 1024
        mock_flag_model.encode.return_value = _make_encode_output([raw])

        result = await embedder.embed_query("test query")

        # After L2 normalization, each element should be 0.5/16 = 0.03125
        expected = 0.5 / (0.5 * (1024 ** 0.5))
        for val in result.values:
            assert abs(val - expected) < 1e-6
