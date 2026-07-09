"""BGE-M3 embedder implementation.

Implements ``EmbedderPort`` using the BAAI/bge-m3 model (1024-dim).

Key contracts:
-``embed()`` embeds ChunkRecord.text
  **verbatim** — no prefix, no summarization, no trimming.
- ``embed_query()`` applies the bge-m3 query instruction prefix so retrieval
  uses the correct asymmetric encoding.
- The same model instance must be used for both ingest and query
"""

from __future__ import annotations

import asyncio
import logging

from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector

logger = logging.getLogger(__name__)

# bge-m3 query instruction prefix.
# Source: BAAI FlagEmbedding docs — for retrieval, queries are prefixed
# with this instruction while documents are encoded as-is.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Batch size for encode() — bge-m3 is memory-heavy; keep batches moderate.
_DEFAULT_BATCH_SIZE = 32


class BgeM3Embedder(EmbedderPort):
    """Concrete embedder backed by ``BAAI/bge-m3`` via FlagEmbedding.

    Uses ``FlagModel`` (CPU/GPU) with dense embeddings, normalized for
    cosine-similarity search in Qdrant.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "cpu",
        normalize_embeddings: bool = True,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        # Lazy import — FlagEmbedding is a heavy dependency; don't penalize
        # import-time / unit tests that mock the port.
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise ImportError(
                "FlagEmbedding is required for BgeM3Embedder. "
                "Install with: pip install FlagEmbedding"
            ) from exc

        self._model_name = model_name
        self._dimension = 1024  # bge-m3 fixed output dim for dense vectors
        self._normalize = normalize_embeddings
        self._batch_size = batch_size
        self._model = BGEM3FlagModel(
            model_name,
            use_fp16=(device != "cpu"),
            device=device,
        )
        logger.info(
            "BgeM3Embedder initialized: model=%s, device=%s, dim=%d",
            model_name,
            device,
            self._dimension,
        )

    # ------------------------------------------------------------------
    # EmbedderPort properties
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    # ------------------------------------------------------------------
    # EmbedderPort methods
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        """Embed document texts **verbatim** (contract C3).

        No prefix, no summarization, no trimming. The caller (ingestion
        pipeline) is responsible for ensuring ``texts`` are the exact
        ``ChunkRecord.text`` values.
        """
        if not texts:
            return []

        logger.debug("Embedding %d document chunks (verbatim)", len(texts))
        embeddings = await self._encode_batch(texts, is_query=False)

        return [
            EmbeddingVector(
                values=emb,
                model_name=self._model_name,
                dimension=self._dimension,
            )
            for emb in embeddings
        ]

    async def embed_query(self, query: str) -> EmbeddingVector:
        """Embed a search query with the bge-m3 query instruction prefix.

        bge-m3 is an asymmetric retriever: documents and queries use
        different encodings. Queries are prefixed with
        ``"Represent this sentence for searching relevant passages: "``
        so the dense vector aligns with document vectors for cosine search.
        """
        if not query or not query.strip():
            raise ValueError("Query must not be empty or whitespace-only")

        prefixed_query = f"{_QUERY_PREFIX}{query}"
        logger.debug("Embedding query (len=%d chars, with prefix)", len(query))

        embeddings = await self._encode_batch([prefixed_query], is_query=True)

        return EmbeddingVector(
            values=embeddings[0],
            model_name=self._model_name,
            dimension=self._dimension,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _encode_batch(
        self,
        texts: list[str],
        is_query: bool,
    ) -> list[list[float]]:
        """Run model.encode in a thread to avoid blocking the event loop.

        FlagEmbedding's ``encode()`` is synchronous and CPU-bound (especially
        on CPU device). Wrapping in ``run_in_executor`` keeps the async
        API non-blocking.
        """

        def _encode() -> list[list[float]]:
            output = self._model.encode(
                texts,
                batch_size=self._batch_size,
                max_length=8192,  # bge-m3 max context
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            # BGEM3FlagModel.encode returns a dict-like with 'dense_vecs'
            dense = output["dense_vecs"]
            # Convert to plain Python lists (model may return numpy arrays)
            vectors = [list(v) for v in dense]

            if self._normalize:
                # L2 normalize in pure Python (avoids numpy dependency)
                vectors = [self._l2_normalize(v) for v in vectors]

            return vectors

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _encode)

    @staticmethod
    def _l2_normalize(vector: list[float]) -> list[float]:
        """L2-normalize a vector for cosine similarity search in Qdrant."""
        import math

        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector  # avoid division by zero — return as-is
        return [x / norm for x in vector]


