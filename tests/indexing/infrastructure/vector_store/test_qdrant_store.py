from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from qdrant_client.models import Distance, PointStruct, ScoredPoint

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.shared.errors.domain_error import StorageError, ValidationError
from knowledgenexus.indexing.infrastructure.vector_store.qdrant_schema import QdrantCollectionConfig
from knowledgenexus.indexing.infrastructure.vector_store.qdrant_store import QdrantVectorStore

VECTOR_SIZE = 1024


@pytest.fixture
def config() -> QdrantCollectionConfig:
    return QdrantCollectionConfig(
        collection_name="test_collection",
        vector_size=VECTOR_SIZE,
        distance=Distance.COSINE,
        payload_indexes=[{"field": "source_type", "type": "keyword"}],
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.get_collections.return_value = MagicMock(collections=[])
    return client


@pytest.fixture
def store(mock_client: AsyncMock, config: QdrantCollectionConfig) -> QdrantVectorStore:
    return QdrantVectorStore(client=mock_client, config=config)


def _chunk(
    *,
    chunk_id: str | None = None,
    vector: list[float] | None = None,
    source_id: str = "src-1",
) -> Chunk:
    doc_id = uuid4()
    core = CoreChunkMetadata(
        document_id=doc_id,
        source_type=SourceType.CONFLUENCE,
        source_id=source_id,
        title="Title",
        url=None,
        chunk_index=0,
        total_chunks=1,
        indexed_at=datetime.now(UTC),
        embedding_model="BAAI/bge-m3",
    )
    return Chunk(
        id=chunk_id or str(uuid4()),
        payload=ChunkPayload(core=core, content="full text", extra={}),
        dense_vector=vector if vector is not None else [0.01] * VECTOR_SIZE,
    )


@pytest.mark.asyncio
async def test_upsert_slim_empty_is_no_op(store: QdrantVectorStore, mock_client: AsyncMock):
    await store.upsert_slim([])

    mock_client.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_slim_missing_vector_raises(store: QdrantVectorStore):
    chunk = _chunk()
    chunk.dense_vector = None

    with pytest.raises(ValidationError, match="missing embedding vector"):
        await store.upsert_slim([chunk])


@pytest.mark.asyncio
async def test_upsert_slim_wrong_vector_size_raises(store: QdrantVectorStore):
    chunk = _chunk(vector=[0.1] * 8)

    with pytest.raises(ValidationError, match="vector size"):
        await store.upsert_slim([chunk])


@pytest.mark.asyncio
async def test_upsert_slim_invalid_chunk_id_raises(store: QdrantVectorStore):
    chunk = _chunk(chunk_id="not-a-uuid")

    with pytest.raises(ValidationError, match="Invalid chunk_id"):
        await store.upsert_slim([chunk])


@pytest.mark.asyncio
async def test_upsert_slim_calls_client_with_slim_payload(
    store: QdrantVectorStore, mock_client: AsyncMock
):
    chunk_id = str(uuid4())
    chunk = _chunk(chunk_id=chunk_id)

    await store.upsert_slim([chunk])

    mock_client.upsert.assert_awaited_once()
    call_kwargs = mock_client.upsert.await_args.kwargs
    assert call_kwargs["collection_name"] == "test_collection"
    points: list[PointStruct] = call_kwargs["points"]
    assert len(points) == 1
    assert points[0].id == chunk_id
    assert len(points[0].vector) == VECTOR_SIZE
    assert points[0].payload == {
        "chunk_id": chunk_id,
        "document_id": str(chunk.document_id),
        "source_type": "CONFLUENCE",
        "source_id": "src-1",
        "chunk_index": 0,
        "indexed_at": chunk.payload.core.indexed_at.isoformat(),
    }
    assert "content" not in points[0].payload


@pytest.mark.asyncio
async def test_search_wrong_query_vector_size_raises(store: QdrantVectorStore):
    with pytest.raises(ValidationError, match="Query vector size"):
        await store.search(dense_vector=[0.1] * 8, top_k=5)


@pytest.mark.asyncio
async def test_search_maps_hits_to_scored_chunks(store: QdrantVectorStore, mock_client: AsyncMock):
    chunk_id = str(uuid4())
    doc_id = str(uuid4())
    indexed_at = datetime.now(UTC).isoformat()
    mock_client.query_points.return_value = MagicMock(points=[
        ScoredPoint(
            id=chunk_id,
            version=1,
            score=0.91,
            payload={
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "source_type": "CONFLUENCE",
                "source_id": "src-42",
                "chunk_index": 2,
                "indexed_at": indexed_at,
            },
            vector=None,
        )
    ])

    results = await store.search(dense_vector=[0.01] * VECTOR_SIZE, top_k=1)

    assert len(results) == 1
    assert results[0].score == 0.91
    assert results[0].chunk.id == chunk_id
    assert results[0].chunk.content == ""
    assert results[0].chunk.payload.core.source_id == "src-42"
    assert results[0].chunk.payload.core.chunk_index == 2


@pytest.mark.asyncio
async def test_search_passes_filters(store: QdrantVectorStore, mock_client: AsyncMock):
    mock_client.query_points.return_value = MagicMock(points=[])

    await store.search(
        dense_vector=[0.01] * VECTOR_SIZE,
        top_k=3,
        filters={"source_type": "CONFLUENCE", "source_id": "abc"},
    )

    call_kwargs = mock_client.query_points.await_args.kwargs
    assert call_kwargs["limit"] == 3
    query_filter = call_kwargs["query_filter"]
    assert query_filter is not None
    assert len(query_filter.must) == 2


@pytest.mark.asyncio
async def test_delete_by_source_id(store: QdrantVectorStore, mock_client: AsyncMock):
    await store.delete_by_source_id(SourceType.CONFLUENCE, "page-99")

    mock_client.delete.assert_awaited_once()
    call_kwargs = mock_client.delete.await_args.kwargs
    assert call_kwargs["collection_name"] == "test_collection"
    assert call_kwargs["points_selector"].must is not None


@pytest.mark.asyncio
async def test_delete_by_document_id(store: QdrantVectorStore, mock_client: AsyncMock):
    doc_id = str(uuid4())
    await store.delete_by_document_id(doc_id)

    mock_client.delete.assert_awaited_once()
    selector = mock_client.delete.await_args.kwargs["points_selector"]
    assert selector.must[0].key == "document_id"


@pytest.mark.asyncio
async def test_delete_by_chunk_ids_empty_is_no_op(store: QdrantVectorStore, mock_client: AsyncMock):
    await store.delete_by_chunk_ids([])

    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_by_chunk_ids(store: QdrantVectorStore, mock_client: AsyncMock):
    chunk_id = str(uuid4())
    await store.delete_by_chunk_ids([chunk_id])

    mock_client.delete.assert_awaited_once()
    selector = mock_client.delete.await_args.kwargs["points_selector"]
    assert selector.points == [chunk_id]


@pytest.mark.asyncio
async def test_get_stats(store: QdrantVectorStore, mock_client: AsyncMock):
    mock_client.get_collection.return_value = MagicMock(
        points_count=7,
        status="green",
    )

    stats = await store.get_stats()

    assert stats == {
        "collection": "test_collection",
        "points_count": 7,
        "vector_size": VECTOR_SIZE,
        "is_hybrid": False,
        "status": "green",
    }


@pytest.mark.asyncio
async def test_health_check_success(store: QdrantVectorStore, mock_client: AsyncMock):
    assert await store.health_check() is True
    mock_client.get_collections.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_check_failure_raises_storage_error(
    store: QdrantVectorStore, mock_client: AsyncMock
):
    mock_client.get_collections.side_effect = ConnectionError("down")

    with pytest.raises(StorageError, match="Qdrant health check failed"):
        await store.health_check()


@pytest.mark.asyncio
async def test_ensure_collection_creates_when_missing(
    store: QdrantVectorStore, mock_client: AsyncMock
):
    mock_client.get_collections.return_value = MagicMock(collections=[])

    await store.ensure_collection()

    mock_client.create_collection.assert_awaited_once()
    mock_client.create_payload_index.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_collection_skips_create_when_exists(
    store: QdrantVectorStore, mock_client: AsyncMock
):
    existing = MagicMock()
    existing.name = "test_collection"
    mock_client.get_collections.return_value = MagicMock(collections=[existing])

    await store.ensure_collection()

    mock_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_create_factory_wires_client_and_collection(tmp_path, monkeypatch):
    yaml_path = tmp_path / "qdrant.collection.yaml"
    yaml_path.write_text(
        """
collection_name: from_yaml
vectors:
  size: 16
  distance: cosine
""",
        encoding="utf-8",
    )

    mock_client = AsyncMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])

    monkeypatch.setattr(
        "knowledgenexus.indexing.infrastructure.vector_store.qdrant_store.AsyncQdrantClient",
        lambda **kwargs: mock_client,
    )

    store = await QdrantVectorStore.create(
        url="http://localhost:6333",
        config_path=str(yaml_path),
        collection_name_override="override_name",
    )

    assert store._config.collection_name == "override_name"
    assert store._config.vector_size == 16
    mock_client.create_collection.assert_awaited_once()
