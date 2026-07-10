from __future__ import annotations

from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.ports.document_repository_port import DocumentRepositoryPort
from knowledgenexus.retrieval.domain.ports.retrieval_document_port import RetrievalDocumentPort



class IndexingDocumentAdapter(RetrievalDocumentPort):

    def __init__(self, doc_repo: DocumentRepositoryPort) -> None:
        self._doc_repo = doc_repo

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        return await self._doc_repo.list_all(limit, offset)

    async def get_by_id(self, document_id: str) -> Document | None:
        return await self._doc_repo.get_by_id(document_id)

    async def delete(self, document_id: str) -> bool:
        return await self._doc_repo.delete(document_id)
