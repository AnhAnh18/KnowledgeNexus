from __future__ import annotations

from knowledgenexus.retrieval.application.use_cases.delete_document import DeleteDocumentUseCase
from knowledgenexus.retrieval.application.use_cases.list_documents import ListDocumentsUseCase
from knowledgenexus.retrieval.application.use_cases.retrieve_chunks import RetrieveChunksUseCase


def get_retrieve_chunks_use_case() -> RetrieveChunksUseCase:
    from knowledgenexus.retrieval.infrastructure.query_adapters import (
        IndexingChunkAdapter,
        IndexingEmbedderAdapter,
        IndexingSearchAdapter,
    )
    from knowledgenexus.shared.di import get_container

    container = get_container()

    embedder_adapter = IndexingEmbedderAdapter(container.get_embedder())
    search_adapter = IndexingSearchAdapter(container.vector_store)
    chunk_adapter = IndexingChunkAdapter(container.chunk_repo)

    # Reranker is optional — only wired when reranker_enabled=True in settings
    reranker = container.get_reranker()

    return RetrieveChunksUseCase(
        query_embedder=embedder_adapter,
        search_port=search_adapter,
        chunk_port=chunk_adapter,
        reranker=reranker,
        rerank_candidate_count=container.settings.rerank_candidate_count,
    )


def build_list_documents_use_case() -> ListDocumentsUseCase:
    from knowledgenexus.retrieval.infrastructure.query_adapters import IndexingDocumentAdapter
    from knowledgenexus.shared.di import get_container

    container = get_container()
    document_adapter = IndexingDocumentAdapter(container.document_repo)

    return ListDocumentsUseCase(document_port=document_adapter)


def build_delete_document_use_case() -> DeleteDocumentUseCase:
    from knowledgenexus.retrieval.infrastructure.query_adapters import (
        IndexingChunkAdapter,
        IndexingDocumentAdapter,
        IndexingSearchAdapter,
    )
    from knowledgenexus.shared.di import get_container

    container = get_container()

    document_adapter = IndexingDocumentAdapter(container.document_repo)
    chunk_adapter = IndexingChunkAdapter(container.chunk_repo)
    search_adapter = IndexingSearchAdapter(container.vector_store)

    return DeleteDocumentUseCase(
        document_port=document_adapter,
        chunk_port=chunk_adapter,
        search_port=search_adapter,
    )
