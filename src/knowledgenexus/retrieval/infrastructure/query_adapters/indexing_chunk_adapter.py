from __future__ import annotations

from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.ports.chunk_repository_port import ChunkRepositoryPort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk
from knowledgenexus.retrieval.domain.ports.retrieval_chunk_port import RetrievalChunkPort



class IndexingChunkAdapter(RetrievalChunkPort):

    def __init__(self, chunk_repo: ChunkRepositoryPort) -> None:
        self._chunk_repo = chunk_repo

    async def hydrate(self, slim_results: list[ScoredChunk]) -> list[ScoredChunk]:
        return await self._chunk_repo.hydrate(slim_results)

    async def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        return await self._chunk_repo.get_by_ids(chunk_ids)

    async def delete_by_document_id(self, document_id: str) -> int:
        return await self._chunk_repo.delete_by_document_id(document_id)
