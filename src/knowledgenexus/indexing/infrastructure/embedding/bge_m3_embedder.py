from __future__ import annotations

import asyncio
import logging

from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector, SparseVector

logger = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-m3"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_DEFAULT_DEVICE = "cpu"
_DEFAULT_BATCH_SIZE = 32
_VECTOR_DIMENSION = 1024
_MAX_CONTEXT_LENGTH = 8192
_DENSE_VECS_KEY = "dense_vecs"
_SPARSE_VECS_KEY = "lexical_weights"


class BgeM3Embedder(EmbedderPort):

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        device: str = _DEFAULT_DEVICE,
        normalize_embeddings: bool = True,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        return_sparse: bool = False,
    ) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise ImportError(
                "FlagEmbedding is required for BgeM3Embedder. "
                "Install with: pip install FlagEmbedding"
            ) from exc

        self._model_name = model_name
        self._dimension = _VECTOR_DIMENSION
        self._normalize = normalize_embeddings
        self._batch_size = batch_size
        self._return_sparse = return_sparse
        self._model = BGEM3FlagModel(
            model_name,
            use_fp16=(device != _DEFAULT_DEVICE),
            device=device,
        )

        logger.info(
            "BgeM3Embedder initialized: model=%s, device=%s, dim=%d, sparse=%s",
            model_name,
            device,
            self._dimension,
            return_sparse,
        )

    @classmethod
    def from_settings(cls, settings) -> BgeM3Embedder:
        from knowledgenexus.indexing.infrastructure.embedding.model_path import resolve_embedding_model_path

        model_name = resolve_embedding_model_path(settings)
        return_sparse = getattr(settings, "retrieval_mode", "dense") == "hybrid"
        return cls(
            model_name=model_name,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
            return_sparse=return_sparse,
        )

    def close(self) -> None:
        self._model = None
        logger.info("BgeM3Embedder closed")

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def supports_sparse(self) -> bool:
        return self._return_sparse

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts:
            return []

        logger.debug("Embedding %d document chunks (verbatim)", len(texts))
        dense_vectors, sparse_vectors = await self._encode_batch(texts, is_query=False)

        results: list[EmbeddingVector] = []
        for i, emb in enumerate(dense_vectors):
            sparse = sparse_vectors[i] if sparse_vectors else None
            results.append(
                EmbeddingVector(
                    values=emb,
                    model_name=self._model_name,
                    dimension=self._dimension,
                    sparse=sparse,
                )
            )
        return results

    async def embed_query(self, query: str) -> EmbeddingVector:
        if not query or not query.strip():
            raise ValueError("Query must not be empty or whitespace-only")

        prefixed_query = f"{_QUERY_PREFIX}{query}"
        logger.debug("Embedding query (len=%d chars, with prefix)", len(query))

        dense_vectors, sparse_vectors = await self._encode_batch([prefixed_query], is_query=True)

        sparse = sparse_vectors[0] if sparse_vectors else None
        return EmbeddingVector(
            values=dense_vectors[0],
            model_name=self._model_name,
            dimension=self._dimension,
            sparse=sparse,
        )

    async def _encode_batch(
        self,
        texts: list[str],
        is_query: bool,
    ) -> tuple[list[list[float]], list[SparseVector | None]]:
        def _encode() -> tuple[list[list[float]], list[SparseVector | None]]:
            output = self._model.encode(
                texts,
                batch_size=self._batch_size,
                max_length=_MAX_CONTEXT_LENGTH,
                return_dense=True,
                return_sparse=self._return_sparse,
                return_colbert_vecs=False,
            )
            dense = output[_DENSE_VECS_KEY]
            vectors = [list(v) for v in dense]
            if self._normalize:
                vectors = [self._l2_normalize(v) for v in vectors]

            sparse_results: list[SparseVector | None] = []
            if self._return_sparse and _SPARSE_VECS_KEY in output:
                for sparse_dict in output[_SPARSE_VECS_KEY]:
                    # BGE-M3 returns {token_id: weight} dict per text
                    if sparse_dict:
                        indices = [int(k) for k in sparse_dict.keys()]
                        values = [float(v) for v in sparse_dict.values()]
                        sparse_results.append(SparseVector(indices=indices, values=values))
                    else:
                        sparse_results.append(None)
            else:
                sparse_results = [None] * len(vectors)

            return vectors, sparse_results

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _encode)

    @staticmethod
    def _l2_normalize(vector: list[float]) -> list[float]:
        import math

        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]


