from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from knowledgenexus.chat.application.use_cases.rag_chat import RagChatUseCase
from knowledgenexus.chat.infrastructure.llm.agent_builder_adapter import LLMProviderError
from knowledgenexus.chat.domain.models.chat_request import ChatRequest
from knowledgenexus.presentation.api.v1.schemas.chat_schema import (
    ChatAnswerSchema,
    ChatRequestSchema,
    ChatResponseSchema,
)
from knowledgenexus.presentation.api.v1.schemas.retrieve_schema import CitationSchema

router = APIRouter(prefix="/api/v1", tags=["chat"])


def get_chat_use_case() -> RagChatUseCase:
    from knowledgenexus.presentation.dependencies import build_rag_chat_use_case
    try:
        return build_rag_chat_use_case()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Chat service unavailable: {e}",
        )


@router.post("/chat", response_model=ChatResponseSchema)
async def chat(
    request: ChatRequestSchema,
    use_case: RagChatUseCase = Depends(get_chat_use_case),
) -> ChatResponseSchema:
    try:
        result = await use_case.execute(ChatRequest(
            question=request.question,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
        ))

        citations = [
            CitationSchema(
                chunk_id=c.chunk_id,
                document_id=str(c.document_id),
                title=c.title,
                url=c.url,
                source_type=c.source_type,
                source_id=c.source_id,
                chunk_index=c.chunk_index,
                total_chunks=c.total_chunks,
                page_id=c.page_id,
                space_key=c.space_key,
                repo=c.repo,
                branch=c.branch,
                file_path=c.file_path,
                symbol=c.symbol,
                line_start=c.line_start,
                line_end=c.line_end,
                heading_path=c.heading_path,
                content_kind=c.content_kind,
                language=c.language,
                source_version=c.source_version,
            )
            for c in result.answer.citations
        ]

        return ChatResponseSchema(
            question=result.question,
            answer=ChatAnswerSchema(
                text=result.answer.text,
                model=result.answer.model,
                citations=citations,
            ),
            retrieved_count=result.retrieved_count,
            latency_ms=result.latency_ms,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error: {e}")
