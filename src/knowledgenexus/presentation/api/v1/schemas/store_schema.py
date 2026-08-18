from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from knowledgenexus.indexing.domain.enums.source_type import SourceType


class CoreChunkMetadataSchema(BaseModel):
    document_id: str
    source_type: SourceType
    source_id: str
    title: str
    url: str | None = None
    chunk_index: int
    total_chunks: int
    indexed_at: datetime
    embedding_model: str


class ChunkStoreItem(BaseModel):
    chunk_id: str
    document_id: str
    vector: list[float]
    core: CoreChunkMetadataSchema
    content: str
    extra: dict[str, Any] = Field(default_factory=dict)


class StoreChunksRequest(BaseModel):
    chunks: list[ChunkStoreItem]


class StoreChunksResponse(BaseModel):
    chunks_stored: int


class StoreStatsResponse(BaseModel):
    qdrant: dict[str, Any]
    sqlite: dict[str, Any]
