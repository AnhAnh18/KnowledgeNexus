from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RetrieveRequestSchema(BaseModel):
    query: str = Field(..., min_length=1, description="Search query text")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results to return")
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum score threshold")
    filters: dict[str, Any] = Field(default_factory=dict, description="Metadata filters")


class CitationSchema(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    url: str | None = None
    source_type: str
    source_id: str
    chunk_index: int
    total_chunks: int
    page_id: str | None = None
    space_key: str | None = None
    repo: str | None = None
    branch: str | None = None
    file_path: str | None = None
    symbol: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    heading_path: str | None = None
    content_kind: str | None = None
    language: str | None = None
    source_version: str | None = None


class RetrievedChunkSchema(BaseModel):
    content: str
    score: float
    citation: CitationSchema


class RetrieveResponseSchema(BaseModel):
    query: str
    total: int
    results: list[RetrievedChunkSchema]
