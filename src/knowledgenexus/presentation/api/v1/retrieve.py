from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from knowledgenexus.presentation.api.v1.schemas.retrieve_schema import (
    RetrieveRequestSchema,
    RetrieveResponseSchema,
    RetrievedChunkSchema,
    CitationSchema,
)
from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase
from knowledgenexus.retrieval.domain.models.retrieve_request import RetrieveRequest

router = APIRouter(prefix="/api/v1", tags=["retrieve"])


def get_retrieve_use_case() -> RetrieveChunksUseCase:
    from knowledgenexus.main import get_retrieve_chunks_use_case
    return get_retrieve_chunks_use_case()


@router.post("/retrieve", response_model=RetrieveResponseSchema)
async def retrieve(
    request: RetrieveRequestSchema,
    use_case: RetrieveChunksUseCase = Depends(get_retrieve_use_case),
) -> RetrieveResponseSchema:
    try:
        domain_request = RetrieveRequest(
            query=request.query,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            filters=request.filters,
        )
        result = await use_case.execute(domain_request)

        results = [
            RetrievedChunkSchema(
                content=r.content,
                score=r.score,
                citation=CitationSchema(
                    chunk_id=r.citation.chunk_id,
                    document_id=str(r.citation.document_id),
                    title=r.citation.title,
                    url=r.citation.url,
                    source_type=r.citation.source_type,
                    source_id=r.citation.source_id,
                    chunk_index=r.citation.chunk_index,
                    total_chunks=r.citation.total_chunks,
                    page_id=r.citation.page_id,
                    space_key=r.citation.space_key,
                    repo=r.citation.repo,
                    branch=r.citation.branch,
                    file_path=r.citation.file_path,
                    symbol=r.citation.symbol,
                    line_start=r.citation.line_start,
                    line_end=r.citation.line_end,
                    heading_path=r.citation.heading_path,
                    content_kind=r.citation.content_kind,
                    language=r.citation.language,
                    source_version=r.citation.source_version,
                ),
            )
            for r in result.results
        ]

        return RetrieveResponseSchema(
            query=result.query,
            total=result.total,
            results=results,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
