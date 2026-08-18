from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from knowledgenexus.indexing.application.use_cases.chunk_storage_service import ChunkStorageService
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.ports.vector_store_port import VectorStorePort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk
from knowledgenexus.indexing.infrastructure.database.engine import create_engine, create_session_factory, init_database
from knowledgenexus.indexing.infrastructure.repositories.sqlite_chunk_repo import SqliteChunkRepository
from knowledgenexus.indexing.infrastructure.repositories.sqlite_document_repo import SqliteDocumentRepository


class InMemoryVectorStore(VectorStorePort):
    def __init__(self) -> None:
        self.points: dict[str, Chunk] = {}

    async def upsert_slim(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            self.points[chunk.id] = chunk

    async def search(
        self, dense_vector: list[float], top_k: int, filters: dict[str, Any] | None = None
    ) -> list[ScoredChunk]:
        results = []
        for chunk in list(self.points.values())[:top_k]:
            if filters:
                core = chunk.payload.core
                if filters.get("source_type") and core.source_type != SourceType(filters["source_type"]):
                    continue
            results.append(ScoredChunk(chunk=chunk, score=0.95))
        return results

    async def delete_by_source_id(self, source_type: SourceType, source_id: str) -> int:
        to_delete = [
            cid
            for cid, c in self.points.items()
            if c.payload.core.source_type == source_type and c.payload.core.source_id == source_id
        ]
        for cid in to_delete:
            del self.points[cid]
        return len(to_delete)

    async def delete_by_document_id(self, document_id: str) -> int:
        to_delete = [
            cid for cid, c in self.points.items() if str(c.document_id) == document_id
        ]
        for cid in to_delete:
            del self.points[cid]
        return len(to_delete)

    async def get_stats(self) -> dict[str, Any]:
        return {"points_count": len(self.points)}


def _chunk(doc_id: UUID) -> Chunk:
    core = CoreChunkMetadata(
        document_id=doc_id,
        source_type=SourceType.CONFLUENCE,
        source_id="99",
        title="T",
        url=None,
        chunk_index=0,
        total_chunks=1,
        indexed_at=datetime.now(UTC),
        embedding_model="test",
    )
    return Chunk(
        id=str(uuid4()),
        payload=ChunkPayload(core=core, content="hello world", extra={"k": "v"}),
        dense_vector=[0.0] * 4,
    )


@pytest.mark.asyncio
async def test_chunk_storage_save_search_hydrate():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_database(engine)
    factory = create_session_factory(engine)
    chunk_repo = SqliteChunkRepository(factory)
    doc_repo = SqliteDocumentRepository(factory)
    vector_store = InMemoryVectorStore()
    storage = ChunkStorageService(vector_store, chunk_repo, doc_repo)

    doc_id = uuid4()
    chunk = _chunk(doc_id)
    await storage.save([chunk])

    results = await storage.search(dense_vector=[0.0] * 4, top_k=5)
    assert len(results) == 1
    assert results[0].chunk.content == "hello world"
    assert results[0].chunk.payload.extra["k"] == "v"

    stats = await storage.get_stats()
    assert stats["sqlite"]["chunks"] == 1
    assert stats["qdrant"]["points_count"] == 1

    await engine.dispose()
