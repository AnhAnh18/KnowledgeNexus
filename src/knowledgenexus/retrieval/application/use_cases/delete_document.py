from __future__ import annotations

import logging

from knowledgenexus.retrieval.domain.ports.retrieval_chunk_port import RetrievalChunkPort
from knowledgenexus.retrieval.domain.ports.retrieval_document_port import RetrievalDocumentPort
from knowledgenexus.retrieval.domain.ports.retrieval_search_port import RetrievalSearchPort

logger = logging.getLogger(__name__)


class DeleteDocumentUseCase:

    def __init__(
        self,
        document_port: RetrievalDocumentPort,
        chunk_port: RetrievalChunkPort,
        search_port: RetrievalSearchPort,
    ) -> None:
        self._document_port = document_port
        self._chunk_port = chunk_port
        self._search_port = search_port

    async def execute(self, document_id: str) -> bool:
        existing = await self._document_port.get_by_id(document_id)
        if existing is None:
            return False

        vectors_deleted = await self._search_port.delete_by_document_id(document_id)
        logger.info("Deleted %d vectors from vector store for document %s", vectors_deleted, document_id)

        chunks_deleted = await self._chunk_port.delete_by_document_id(document_id)
        logger.info("Deleted %d chunks from SQLite for document %s", chunks_deleted, document_id)

        await self._document_port.delete(document_id)
        logger.info("Deleted document record for %s", document_id)

        return True
