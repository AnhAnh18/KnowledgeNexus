from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.infrastructure.database.engine import create_engine, create_session_factory, init_database
from knowledgenexus.indexing.infrastructure.repositories.sqlite_chunk_repo import SqliteChunkRepository
from knowledgenexus.indexing.infrastructure.repositories.sqlite_document_repo import SqliteDocumentRepository


def _make_core(document_id: UUID, chunk_index: int = 0) -> CoreChunkMetadata:
    return CoreChunkMetadata(
        document_id=document_id,
        source_type=SourceType.CONFLUENCE,
        source_id="page-1",
        title="Test Doc",
        url="https://example.com",
        chunk_index=chunk_index,
        total_chunks=2,
        indexed_at=datetime.now(UTC),
        embedding_model="BAAI/bge-m3",
    )


def _make_chunk(chunk_id: str, document_id: UUID, chunk_index: int, content: str) -> Chunk:
    core = _make_core(document_id, chunk_index)
    return Chunk(
        id=chunk_id,
        payload=ChunkPayload(core=core, content=content, extra={"space_key": "DEV"}),
        vector=[0.1] * 4,
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_database(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_document_repo_save_and_get(session_factory):
    repo = SqliteDocumentRepository(session_factory)
    doc_id = uuid4()
    doc = Document(
        id=doc_id,
        title="Deploy Guide",
        content="full text",
        source_type=SourceType.CONFLUENCE,
        source_id="42",
        url="https://wiki.example.com/42",
        metadata={"space_key": "DEV"},
    )
    await repo.save(doc)
    loaded = await repo.get_by_id(str(doc_id))
    assert loaded is not None
    assert loaded.title == "Deploy Guide"
    assert loaded.metadata["space_key"] == "DEV"

    by_source = await repo.get_by_source(SourceType.CONFLUENCE, "42")
    assert by_source is not None
    assert str(by_source.id) == str(doc_id)


@pytest.mark.asyncio
async def test_chunk_repo_save_hydrate_and_delete(session_factory):
    repo = SqliteChunkRepository(session_factory)
    doc_id = uuid4()
    chunk1 = _make_chunk(str(uuid4()), doc_id, 0, "chunk one")
    chunk2 = _make_chunk(str(uuid4()), doc_id, 1, "chunk two")
    await repo.save_batch([chunk1, chunk2])

    loaded = await repo.get_by_document_id(str(doc_id))
    assert len(loaded) == 2
    assert loaded[0].content == "chunk one"
    assert loaded[1].payload.extra["space_key"] == "DEV"

    from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk

    slim_payload = ChunkPayload(core=chunk1.payload.core, content="", extra={})
    slim = [ScoredChunk(chunk=Chunk(id=chunk1.id, payload=slim_payload), score=0.9)]
    hydrated = await repo.hydrate(slim)
    assert hydrated[0].chunk.content == "chunk one"
    assert hydrated[0].score == 0.9

    deleted = await repo.delete_by_source_id(SourceType.CONFLUENCE, "page-1")
    assert deleted == 2
    assert await repo.count() == 0
