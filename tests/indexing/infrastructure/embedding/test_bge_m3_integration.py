from __future__ import annotations

import math
import os

import pytest

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector

# Local offline model path
_LOCAL_MODEL_PATH = r"D:\Tools\BAAI_bge-m3"


@pytest.fixture(scope="module")
def embedder():
    """Load the real BGE-M3 model once for all tests in this module."""
    pytest.importorskip("FlagEmbedding", reason="FlagEmbedding not installed")

    if not os.path.isdir(_LOCAL_MODEL_PATH):
        pytest.skip(f"BGE-M3 model not found at: {_LOCAL_MODEL_PATH}")

    from knowledgenexus.indexing.infrastructure.embedding.bge_m3_embedder import BgeM3Embedder

    instance = BgeM3Embedder(model_name=_LOCAL_MODEL_PATH, device="cpu")
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Integration: embed_query (1 câu → vector 1024)
# ---------------------------------------------------------------------------

class TestBgeM3IntegrationEmbedQuery:
    """Test: embed_query with real BGE-M3 model — 1 query → 1024-dim vector."""

    @pytest.mark.asyncio
    async def test_embed_query_returns_1024_dim_vector(self, embedder):
        query = "How to configure Qdrant vector database?"

        result = await embedder.embed_query(query)

        # Must return EmbeddingVector
        assert isinstance(result, EmbeddingVector), f"Expected EmbeddingVector, got {type(result)}"

        # Must be 1024 dimensions
        assert result.dimension == 1024, f"Expected dimension 1024, got {result.dimension}"
        assert len(result.values) == 1024, f"Expected 1024 values, got {len(result.values)}"

        # Model name must match the local path used
        assert result.model_name == _LOCAL_MODEL_PATH

    @pytest.mark.asyncio
    async def test_embed_query_vector_is_l2_normalized(self, embedder):
        result = await embedder.embed_query("What is machine learning?")

        norm = math.sqrt(sum(x * x for x in result.values))
        assert abs(norm - 1.0) < 1e-5, f"L2 norm should be ~1.0, got {norm}"

    @pytest.mark.asyncio
    async def test_embed_query_different_queries_produce_different_vectors(self, embedder):
        v1 = await embedder.embed_query("How to cook pasta?")
        v2 = await embedder.embed_query("How to deploy Kubernetes?")

        # Cosine similarity should be < 0.99 (different topics)
        dot = sum(a * b for a, b in zip(v1.values, v2.values, strict=True))
        assert dot < 0.99, f"Different queries should produce different vectors, cosine={dot}"

    @pytest.mark.asyncio
    async def test_embed_query_same_query_produces_same_vector(self, embedder):
        query = "What is the capital of France?"

        v1 = await embedder.embed_query(query)
        v2 = await embedder.embed_query(query)

        for a, b in zip(v1.values, v2.values, strict=True):
            assert abs(a - b) < 1e-6, "Same query should produce identical vectors"


# ---------------------------------------------------------------------------
# Integration: embed (document chunks)
# ---------------------------------------------------------------------------

class TestBgeM3IntegrationEmbed:
    """Test: embed with real BGE-M3 model — multiple texts → 1024-dim vectors."""

    @pytest.mark.asyncio
    async def test_embed_single_text_returns_1024_dim(self, embedder):
        result = await embedder.embed(["Python is a popular programming language."])

        assert len(result) == 1
        assert isinstance(result[0], EmbeddingVector)
        assert result[0].dimension == 1024
        assert len(result[0].values) == 1024

    @pytest.mark.asyncio
    async def test_embed_multiple_texts_returns_multiple_vectors(self, embedder):
        texts = [
            "Python is a programming language.",
            "Qdrant is a vector database.",
            "FastAPI is a web framework.",
        ]

        result = await embedder.embed(texts)

        assert len(result) == 3
        for vec in result:
            assert isinstance(vec, EmbeddingVector)
            assert vec.dimension == 1024
            assert len(vec.values) == 1024

    @pytest.mark.asyncio
    async def test_embed_empty_list_returns_empty(self, embedder):
        """Empty list → empty list."""
        result = await embedder.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_vectors_are_l2_normalized(self, embedder):
        result = await embedder.embed(["Test normalization of embedding vectors."])

        norm = math.sqrt(sum(x * x for x in result[0].values))
        assert abs(norm - 1.0) < 1e-5, f"L2 norm should be ~1.0, got {norm}"
