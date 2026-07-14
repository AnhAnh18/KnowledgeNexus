from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from knowledgenexus.presentation.api.v1.schemas.document_schema import (
    DocumentSchema,
    ListDocumentsResponseSchema,
)
from knowledgenexus.retrieval.application.use_cases.delete_document import DeleteDocumentUseCase
from knowledgenexus.retrieval.application.use_cases.list_documents import (
    ListDocumentsRequest,
    ListDocumentsUseCase,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])


def get_list_documents_use_case() -> ListDocumentsUseCase:
    from knowledgenexus.presentation.dependencies import build_list_documents_use_case
    return build_list_documents_use_case()


@router.get("/documents", response_model=ListDocumentsResponseSchema)
async def list_documents(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    use_case: ListDocumentsUseCase = Depends(get_list_documents_use_case),
) -> ListDocumentsResponseSchema:
    result = await use_case.execute(ListDocumentsRequest(limit=limit, offset=offset))

    documents = [
        DocumentSchema(
            id=doc.id,
            title=doc.title,
            source_type=doc.source_type.value,
            source_id=doc.source_id,
            url=doc.url,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc in result.documents
    ]

    return ListDocumentsResponseSchema(
        documents=documents,
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


def get_delete_document_use_case() -> DeleteDocumentUseCase:
    from knowledgenexus.presentation.dependencies import build_delete_document_use_case
    return build_delete_document_use_case()


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    use_case: DeleteDocumentUseCase = Depends(get_delete_document_use_case),
) -> None:
    deleted = await use_case.execute(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found",
        )
