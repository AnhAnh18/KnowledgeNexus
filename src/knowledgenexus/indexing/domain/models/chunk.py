from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from knowledgenexus.indexing.domain.enums import SourceType


@dataclass
class CoreChunkMetadata:
    document_id: UUID
    source_type: SourceType
    source_id: str
    title: str
    url: str | None
    chunk_index: int
    total_chunks: int
    indexed_at: datetime
    embedding_model: str


@dataclass
class ChunkPayload:
    core: CoreChunkMetadata
    content: str    # full text - persisted in SQLite chunks.content
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class Chunk:
    id: str     # chunk PK - UUID string or AKP chunk_id
    payload: ChunkPayload
    vector: list[float] | None = None
    
    @property
    def document_id(self) -> UUID:
        return self.payload.core.document_id
    
    @property
    def chunk_index(self) -> int:
        return self.payload.core.chunk_index
    
    @property
    def content(self) -> str:
        return self.payload.content
