from typing import Any

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.ports.chunk_repository_port import ChunkRepositoryPort
from knowledgenexus.indexing.domain.ports.document_repository_port import DocumentRepositoryPort
from knowledgenexus.indexing.domain.ports.vector_store_port import VectorStorePort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk


class ChunkStorageService:

    def __init__(
        self,
        vector_store: VectorStorePort,
        chunk_repo: ChunkRepositoryPort,
        document_repo: DocumentRepositoryPort | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._chunk_repo = chunk_repo
        self._document_repo = document_repo

    async def save_document_and_chunks(
        self, document: Document, chunks: list[Chunk]
    ) -> None:
        if self._document_repo is not None:
            await self._document_repo.save(document)
        await self._chunk_repo.save_batch(chunks)
        await self._vector_store.upsert_slim(chunks)

    async def save_documents_and_chunks(
        self, documents: list[Document], chunks: list[Chunk]
    ) -> None:
        """Persist a whole packet: many documents plus their chunks.

        `save_document_and_chunks` takes a single document, which is why the
        packet path used to call `save` instead and silently dropped every
        document record -- leaving the documents table empty even after a
        successful subtree ingest. Documents are written first so a chunk
        never lands before the row it belongs to.
        """
        if self._document_repo is not None:
            for document in documents:
                await self._document_repo.save(document)
        await self._chunk_repo.save_batch(chunks)
        await self._vector_store.upsert_slim(chunks)

    async def save(self, chunks: list[Chunk]) -> None:
        await self._chunk_repo.save_batch(chunks)
        await self._vector_store.upsert_slim(chunks)

    async def search(
        self,
        dense_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        slim_results = await self._vector_store.search(dense_vector, top_k, filters)
        return await self._chunk_repo.hydrate(slim_results)

    async def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        return await self._chunk_repo.get_by_ids(chunk_ids)

    async def delete_by_source_id(self, source_type: SourceType, source_id: str) -> None:
        await self._chunk_repo.delete_by_source_id(source_type, source_id)
        await self._vector_store.delete_by_source_id(source_type, source_id)

    async def delete_by_document_id(self, document_id: str) -> None:
        await self._chunk_repo.delete_by_document_id(document_id)
        await self._vector_store.delete_by_document_id(document_id)

    async def get_stats(self) -> dict[str, Any]:
        qdrant_stats = await self._vector_store.get_stats()
        sqlite_stats: dict[str, Any] = {}
        if hasattr(self._chunk_repo, "count"):
            sqlite_stats["chunks"] = await self._chunk_repo.count()
        if self._document_repo is not None and hasattr(self._document_repo, "count"):
            sqlite_stats["documents"] = await self._document_repo.count()
        return {"qdrant": qdrant_stats, "sqlite": sqlite_stats}
