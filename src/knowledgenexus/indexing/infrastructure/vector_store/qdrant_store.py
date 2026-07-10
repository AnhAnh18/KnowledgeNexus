from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.shared.errors import StorageError, ValidationError
from knowledgenexus.indexing.domain.ports.vector_store_port import VectorStorePort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk

from knowledgenexus.indexing.infrastructure.vector_store.qdrant_schema import (
    QdrantCollectionConfig,
    index_type_from_config,
    load_qdrant_collection_config,
)


def _to_point_id(chunk_id: str) -> str:
    try:
        UUID(chunk_id)
        return chunk_id
    except ValueError:
        raise ValidationError(f"Invalid chunk_id for Qdrant point: {chunk_id}") from None


def _slim_payload(chunk: Chunk) -> dict[str, Any]:
    core = chunk.payload.core
    indexed_at = core.indexed_at
    if isinstance(indexed_at, datetime):
        indexed_at = indexed_at.isoformat()
    return {
        "chunk_id": chunk.id,
        "document_id": str(core.document_id),
        "source_type": str(core.source_type),
        "source_id": core.source_id,
        "chunk_index": core.chunk_index,
        "indexed_at": indexed_at,
    }


def _build_filter(filters: dict[str, Any] | None) -> Filter | None:
    if not filters:
        return None
    conditions = [
        FieldCondition(key=key, match=MatchValue(value=value))
        for key, value in filters.items()
        if value is not None
    ]
    return Filter(must=conditions) if conditions else None


def _slim_chunk_from_payload(payload: dict[str, Any], score: float) -> ScoredChunk:
    from knowledgenexus.indexing.domain.models.chunk import ChunkPayload, CoreChunkMetadata

    indexed_at = payload.get("indexed_at")
    if isinstance(indexed_at, str):
        indexed_at = datetime.fromisoformat(indexed_at)
    elif not isinstance(indexed_at, datetime):
        indexed_at = datetime.utcnow()

    chunk_id = str(payload["chunk_id"])
    core = CoreChunkMetadata(
        document_id=UUID(str(payload["document_id"])),
        source_type=SourceType(str(payload["source_type"])),
        source_id=str(payload["source_id"]),
        title="",
        url=None,
        chunk_index=int(payload["chunk_index"]),
        total_chunks=1,
        indexed_at=indexed_at,
        embedding_model="",
    )
    slim_chunk = Chunk(
        id=chunk_id,
        payload=ChunkPayload(core=core, content="", extra={}),
    )
    return ScoredChunk(chunk=slim_chunk, score=score)


class QdrantVectorStore(VectorStorePort):
    def __init__(
        self,
        client: AsyncQdrantClient,
        config: QdrantCollectionConfig,
    ) -> None:
        self._client = client
        self._config = config

    @classmethod
    async def create(
        cls,
        url: str,
        config_path: str,
        api_key: str | None = None,
        collection_name_override: str | None = None,
    ) -> "QdrantVectorStore":
        config = load_qdrant_collection_config(Path(config_path))
        if collection_name_override:
            config = QdrantCollectionConfig(
                collection_name=collection_name_override,
                vector_size=config.vector_size,
                distance=config.distance,
                payload_indexes=config.payload_indexes,
            )
        client = AsyncQdrantClient(url=url, api_key=api_key)
        store = cls(client=client, config=config)
        await store.ensure_collection()
        return store

    async def ensure_collection(self) -> None:
        collections = await self._client.get_collections()
        names = {c.name for c in collections.collections}
        if self._config.collection_name not in names:
            await self._client.create_collection(
                collection_name=self._config.collection_name,
                vectors_config=VectorParams(
                    size=self._config.vector_size,
                    distance=self._config.distance,
                ),
            )
        for index_def in self._config.payload_indexes:
            try:
                await self._client.create_payload_index(
                    collection_name=self._config.collection_name,
                    field_name=index_def["field"],
                    field_schema=index_type_from_config(index_def),
                )
            except Exception:
                # Index may already exist on collection re-init
                pass

    async def upsert_slim(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        points: list[PointStruct] = []
        for chunk in chunks:
            if chunk.vector is None:
                raise ValidationError(f"Chunk {chunk.id} missing embedding vector")
            if len(chunk.vector) != self._config.vector_size:
                raise ValidationError(
                    f"Chunk {chunk.id} vector size {len(chunk.vector)} "
                    f"!= expected {self._config.vector_size}"
                )
            points.append(
                PointStruct(
                    id=_to_point_id(chunk.id),
                    vector=chunk.vector,
                    payload=_slim_payload(chunk),
                )
            )
        await self._client.upsert(collection_name=self._config.collection_name, points=points)

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        if len(query_vector) != self._config.vector_size:
            raise ValidationError(
                f"Query vector size {len(query_vector)} != {self._config.vector_size}"
            )
        results = await self._client.search(
            collection_name=self._config.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=_build_filter(filters),
        )
        return [
            _slim_chunk_from_payload(hit.payload or {}, hit.score or 0.0) for hit in results
        ]

    async def delete_by_source_id(self, source_type: SourceType, source_id: str) -> int:
        await self._client.delete(
            collection_name=self._config.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="source_type", match=MatchValue(value=str(source_type))),
                    FieldCondition(key="source_id", match=MatchValue(value=source_id)),
                ]
            ),
        )
        return 0  # Qdrant delete does not return count

    async def delete_by_document_id(self, document_id: str) -> int:
        await self._client.delete(
            collection_name=self._config.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        return 0

    async def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        await self._client.delete(
            collection_name=self._config.collection_name,
            points_selector=PointIdsList(points=[_to_point_id(cid) for cid in chunk_ids]),
        )

    async def get_stats(self) -> dict[str, Any]:
        info = await self._client.get_collection(self._config.collection_name)
        return {
            "collection": self._config.collection_name,
            "points_count": info.points_count,
            "vector_size": self._config.vector_size,
            "status": str(info.status),
        }

    async def health_check(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            raise StorageError(f"Qdrant health check failed: {exc}") from exc

    async def close(self) -> None:
        await self._client.close()
