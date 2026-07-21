from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRequest:
    question: str
    top_k: int = 5
    score_threshold: float = 0.0
