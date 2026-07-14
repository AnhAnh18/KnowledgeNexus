from __future__ import annotations

from dataclasses import dataclass

from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.retrieval.domain.ports.retrieval_document_port import RetrievalDocumentPort


@dataclass
class ListDocumentsRequest:
    limit: int = 100
    offset: int = 0


@dataclass
class ListDocumentsResult:
    documents: list[Document]
    total: int
    limit: int
    offset: int


class ListDocumentsUseCase:

    def __init__(self, document_port: RetrievalDocumentPort) -> None:
        self._document_port = document_port

    async def execute(self, request: ListDocumentsRequest) -> ListDocumentsResult:
        documents = await self._document_port.list_all(
            limit=request.limit,
            offset=request.offset,
        )
        return ListDocumentsResult(
            documents=documents,
            total=len(documents),
            limit=request.limit,
            offset=request.offset,
        )
