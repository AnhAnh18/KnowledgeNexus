from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    document_id: UUID
    title: str
    url: str | None
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


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    citation: Citation


@dataclass(frozen=True)
class RetrieveResult:
    query: str
    total: int
    results: list[RetrievedChunk]
