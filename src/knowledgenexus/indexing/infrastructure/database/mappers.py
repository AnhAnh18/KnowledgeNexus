from datetime import datetime
from uuid import UUID

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.models.document import Document

from knowledgenexus.indexing.infrastructure.database.models import ChunkModel, DocumentModel


def document_to_model(document: Document) -> DocumentModel:
    return DocumentModel(
        id=str(document.id),
        title=document.title,
        source_type=str(document.source_type),
        source_id=document.source_id,
        url=document.url,
        metadata_json=document.metadata,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def document_from_model(model: DocumentModel) -> Document:
    return Document(
        id=UUID(model.id),
        title=model.title,
        content="",  # content lives in chunks; populated by use cases when needed
        source_type=SourceType(model.source_type),
        source_id=model.source_id,
        url=model.url,
        metadata=model.metadata_json or {},
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def chunk_to_model(chunk: Chunk) -> ChunkModel:
    core = chunk.payload.core
    return ChunkModel(
        id=chunk.id,
        document_id=str(core.document_id),
        chunk_index=core.chunk_index,
        content=chunk.payload.content,
        core_metadata={
            "document_id": str(core.document_id),
            "source_type": str(core.source_type),
            "source_id": core.source_id,
            "title": core.title,
            "url": core.url,
            "chunk_index": core.chunk_index,
            "total_chunks": core.total_chunks,
            "indexed_at": core.indexed_at.isoformat(),
            "embedding_model": core.embedding_model,
        },
        extra=chunk.payload.extra,
        indexed_at=core.indexed_at,
        source_type=str(core.source_type),
        source_id=core.source_id,
    )


def chunk_from_model(model: ChunkModel) -> Chunk:
    core_data = model.core_metadata
    indexed_at = core_data.get("indexed_at")
    if isinstance(indexed_at, str):
        indexed_at = datetime.fromisoformat(indexed_at)
    elif not isinstance(indexed_at, datetime):
        indexed_at = model.indexed_at

    core = CoreChunkMetadata(
        document_id=UUID(core_data["document_id"]),
        source_type=SourceType(core_data["source_type"]),
        source_id=core_data["source_id"],
        title=core_data["title"],
        url=core_data.get("url"),
        chunk_index=core_data["chunk_index"],
        total_chunks=core_data["total_chunks"],
        indexed_at=indexed_at,
        embedding_model=core_data["embedding_model"],
    )
    payload = ChunkPayload(core=core, content=model.content, extra=model.extra or {})
    return Chunk(
        id=model.id,
        payload=payload,
    )

