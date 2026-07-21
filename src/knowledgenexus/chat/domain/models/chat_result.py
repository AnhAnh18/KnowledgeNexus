from __future__ import annotations

from dataclasses import dataclass, field

from knowledgenexus.retrieval.domain.models.retrieve_result import Citation


@dataclass(frozen=True)
class ChatAnswer:
    text: str
    model: str
    citations: list[Citation] = field(default_factory=list)


@dataclass(frozen=True)
class ChatResult:
    question: str
    answer: ChatAnswer
    retrieved_count: int
    latency_ms: int
