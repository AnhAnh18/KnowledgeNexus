from __future__ import annotations

import asyncio
import logging

from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector

logger = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-m3"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_DEFAULT_DEVICE = "cpu"
_DEFAULT_BATCH_SIZE = 32
_VECTOR_DIMENSION = 1024
_MAX_CONTEXT_LENGTH = 8192
_DENSE_VECS_KEY = "dense_vecs"


class BgeM3Embedder(EmbedderPort):

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        device: str = _DEFAULT_DEVICE,
        normalize_embeddings: bool = True,
        batch_size: int = _DEFAULT_BATCH_SIZE,
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
        self._model = BGEM3FlagModel(
            model_name,
            use_fp16=(device != _DEFAULT_DEVICE),
            device=device,
        )

        logger.info(
            "BgeM3Embedder initialized: model=%s, device=%s, dim=%d",
            model_name,
            device,
            self._dimension,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension


    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
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

    async def _encode_batch(
        self,
        texts: list[str],
        is_query: bool,
    ) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            output = self._model.encode(
                texts,
                batch_size=self._batch_size,
                max_length=_MAX_CONTEXT_LENGTH,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = output[_DENSE_VECS_KEY]

            vectors = [list(v) for v in dense]

            if self._normalize:
                vectors = [self._l2_normalize(v) for v in vectors]

            return vectors

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _encode)

    @staticmethod
    def _l2_normalize(vector: list[float]) -> list[float]:
        import math

        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]


