from dataclasses import dataclass

from knowledgenexus.indexing.domain.models.chunk import Chunk


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
