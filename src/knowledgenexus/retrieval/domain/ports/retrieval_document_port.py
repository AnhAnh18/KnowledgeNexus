from __future__ import annotations

from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.models.document import Document


class RetrievalDocumentPort(ABC):

    @abstractmethod
    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        ...

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Document | None:
        ...

    @abstractmethod
    async def delete(self, document_id: str) -> bool:
        ...
