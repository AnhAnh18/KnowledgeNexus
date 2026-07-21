from __future__ import annotations

from knowledgenexus.chat.application.use_cases.rag_chat import RagChatUseCase
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

    return RetrieveChunksUseCase(
        query_embedder=embedder_adapter,
        search_port=search_adapter,
        chunk_port=chunk_adapter,
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


def build_rag_chat_use_case() -> RagChatUseCase:
    from knowledgenexus.chat.infrastructure.llm import AgentBuilderAdapter
    from knowledgenexus.chat.infrastructure.retrieval_adapter import RetrievalAdapter
    from knowledgenexus.shared.di import get_container

    container = get_container()
    settings = container.settings

    retrieve_use_case = get_retrieve_chunks_use_case()
    retrieval_port = RetrievalAdapter(retrieve_use_case)

    llm = AgentBuilderAdapter(
        base_url=settings.agent_builder_api_url,
        api_key=settings.agent_builder_api_key,
        agent_id=settings.agent_builder_agent_id,
        timeout=settings.agent_builder_timeout,
    )

    return RagChatUseCase(retrieval_port=retrieval_port, llm=llm)
