from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.shared.di.container import AppContainer, get_container
from knowledgenexus.presentation.api.v1.schemas.store_schema import (
    StoreChunksRequest,
    StoreChunksResponse,
    StoreStatsResponse,
)

router = APIRouter(prefix="/api/v1/store", tags=["store"])


def _container() -> AppContainer:
    return get_container()


def _to_chunk(item) -> Chunk:
    document_id = UUID(item.core.document_id)
    if UUID(item.document_id) != document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_id must match core.document_id",
        )
    core = CoreChunkMetadata(
        document_id=document_id,
        source_type=item.core.source_type,
        source_id=item.core.source_id,
        title=item.core.title,
        url=item.core.url,
        chunk_index=item.core.chunk_index,
        total_chunks=item.core.total_chunks,
        indexed_at=item.core.indexed_at,
        embedding_model=item.core.embedding_model,
    )
    payload = ChunkPayload(core=core, content=item.content, extra=item.extra)
    return Chunk(
        id=item.chunk_id,
        payload=payload,
        vector=item.vector,
    )


@router.post("/chunks", response_model=StoreChunksResponse)
async def store_chunks(
    body: StoreChunksRequest,
    container: AppContainer = Depends(_container),
) -> StoreChunksResponse:
    if not body.chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No chunks provided")
    chunks = [_to_chunk(item) for item in body.chunks]
    await container.chunk_storage.save(chunks)
    return StoreChunksResponse(chunks_stored=len(chunks))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    container: AppContainer = Depends(_container),
) -> Response:
    await container.chunk_storage.delete_by_document_id(document_id)
    await container.document_repo.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=StoreStatsResponse)
async def get_store_stats(
    container: AppContainer = Depends(_container),
) -> StoreStatsResponse:
    stats = await container.chunk_storage.get_stats()
    return StoreStatsResponse(**stats)
