from __future__ import annotations

from pydantic import BaseModel, Field

from .retrieve_schema import CitationSchema


class ChatRequestSchema(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class ChatAnswerSchema(BaseModel):
    text: str
    model: str
    citations: list[CitationSchema] = Field(default_factory=list)


class ChatResponseSchema(BaseModel):
    question: str
    answer: ChatAnswerSchema
    retrieved_count: int
    latency_ms: int
