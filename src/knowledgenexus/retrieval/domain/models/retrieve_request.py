from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrieveRequest:
    query: str
    top_k: int = 5
    score_threshold: float = 0.0
    filters: dict[str, Any] = field(default_factory=dict)
