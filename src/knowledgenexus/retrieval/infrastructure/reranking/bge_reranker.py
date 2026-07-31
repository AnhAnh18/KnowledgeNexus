from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk
from knowledgenexus.retrieval.domain.ports.reranker_port import RerankerPort

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
_DEFAULT_DEVICE = "cpu"
_DEFAULT_BATCH_SIZE = 16
_DEFAULT_MAX_LENGTH = 512


class BgeReranker(RerankerPort):
    """Cross-encoder reranker using BAAI/bge-reranker-v2-m3.

    Unlike bi-encoders (BGE-M3) that embed query and document independently,
    a cross-encoder jointly encodes the [query, document] pair, producing a
    single relevance score. This typically yields +10-20 MRR/NDCG improvement
    over dense/sparse retrieval alone.

    The reranker is a post-retrieval stage:
        retrieve top-N (hybrid) → rerank → return top-K

    It requires no additional vector storage and no re-ingestion.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        device: str = _DEFAULT_DEVICE,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        max_length: int = _DEFAULT_MAX_LENGTH,
    ) -> None:
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise ImportError(
                "FlagEmbedding is required for BgeReranker. "
                "Install with: pip install FlagEmbedding"
            ) from exc

        self._model_name = model_name
        self._batch_size = batch_size
        self._max_length = max_length
        self._model = FlagReranker(
            model_name,
            use_fp16=(device != _DEFAULT_DEVICE),
            device=device,
        )

        logger.info(
            "BgeReranker initialized: model=%s, device=%s, batch_size=%d",
            model_name,
            device,
            batch_size,
        )

    @classmethod
    def from_settings(cls, settings) -> BgeReranker | None:
        """Create a BgeReranker from settings, or return None if disabled.

        Model resolution priority (same pattern as BgeM3Embedder):
        1. RERANKER_MODEL_PATH — local folder (symlink or copied weights)
        2. RERANKER_MODEL — HuggingFace repo id (downloads to cache)
        """
        if not getattr(settings, "reranker_enabled", False):
            return None

        model_name = _resolve_reranker_model_path(settings)
        device = getattr(settings, "reranker_device", _DEFAULT_DEVICE)
        batch_size = getattr(settings, "reranker_batch_size", _DEFAULT_BATCH_SIZE)
        return cls(
            model_name=model_name,
            device=device,
            batch_size=batch_size,
        )

    def close(self) -> None:
        self._model = None
        logger.info("BgeReranker closed")

    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        if not candidates:
            return []

        if not query or not query.strip():
            raise ValueError("Query must not be empty or whitespace-only")

        # Extract document content from candidate chunks
        pairs: list[list[str]] = []
        for sc in candidates:
            content = sc.chunk.content or ""
            pairs.append([query, content])

        logger.debug(
            "Reranking %d candidates for query (len=%d chars)",
            len(candidates),
            len(query),
        )

        scores = await self._compute_scores(pairs)

        # Build reranked list with new scores
        reranked: list[ScoredChunk] = []
        for sc, score in zip(candidates, scores):
            reranked.append(
                ScoredChunk(
                    chunk=sc.chunk,
                    score=float(score),
                )
            )

        # Sort by reranker score descending and truncate
        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked[:top_k]

    async def _compute_scores(self, pairs: list[list[str]]) -> list[float]:
        """Compute cross-encoder scores for query-document pairs.

        Runs the model in a thread executor to avoid blocking the event loop.
        """

        def _score() -> list[float]:
            return self._model.compute_score(
                pairs,
                batch_size=self._batch_size,
                max_length=self._max_length,
                normalize=True,  # Normalize scores to [0, 1] range
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _score)

        # FlagReranker may return a single float for one pair or a list
        if isinstance(result, float):
            return [result]
        return [float(s) for s in result]


def _resolve_reranker_model_path(settings) -> str:
    """Resolve model location for FlagReranker.

    Priority (same pattern as resolve_embedding_model_path):
    1. RERANKER_MODEL_PATH — local folder (symlink or copied weights)
    2. RERANKER_MODEL — HuggingFace repo id (downloads to cache)
    """
    model_path = getattr(settings, "reranker_model_path", None)
    if model_path:
        raw = Path(model_path)
        path = raw if raw.is_absolute() else settings.project_root / raw
        if path.exists():
            return str(path.resolve())
        raise FileNotFoundError(
            f"RERANKER_MODEL_PATH does not exist: {path}. "
            "Point to a local bge-reranker-v2-m3 folder or symlink."
        )
    return getattr(settings, "reranker_model", _DEFAULT_MODEL)
