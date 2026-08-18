"""Eval data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


MatchOn = Literal["document_id", "chunk_id", "source_id"]
LayerName = Literal["1", "2", "all"]


@dataclass(frozen=True)
class GoldenCase:
    id: str
    user_question: str
    search_query: str
    relevant_chunk_ids: tuple[str, ...] = ()
    relevant_document_ids: tuple[str, ...] = ()
    relevant_source_ids: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    source: str = "manual"

    def relevant_ids(self, match_on: MatchOn) -> set[str]:
        if match_on == "chunk_id":
            return set(self.relevant_chunk_ids)
        if match_on == "source_id":
            return set(self.relevant_source_ids)
        return set(self.relevant_document_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_question": self.user_question,
            "search_query": self.search_query,
            "relevant_chunk_ids": list(self.relevant_chunk_ids),
            "relevant_document_ids": list(self.relevant_document_ids),
            "relevant_source_ids": list(self.relevant_source_ids),
            "filters": dict(self.filters),
            "tags": list(self.tags),
            "source": self.source,
        }


@dataclass
class CaseLayerResult:
    case_id: str
    hit_at_5: bool
    hit_at_10: bool
    mrr: float
    retrieved_ids: list[str]
    planned_query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LayerMetrics:
    hit_at_5: float
    hit_at_10: float
    mrr: float
    n_cases: int
    n_skipped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalRunResult:
    run_id: str
    label: str
    created_at: str
    config: dict[str, Any]
    layer1: LayerMetrics | None
    layer2: LayerMetrics | None
    gap: dict[str, float] | None
    per_case_layer1: list[CaseLayerResult] = field(default_factory=list)
    per_case_layer2: list[CaseLayerResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "created_at": self.created_at,
            "config": self.config,
            "layer1": self.layer1.to_dict() if self.layer1 else None,
            "layer2": self.layer2.to_dict() if self.layer2 else None,
            "gap": self.gap,
            "per_case_layer1": [c.to_dict() for c in self.per_case_layer1],
            "per_case_layer2": [c.to_dict() for c in self.per_case_layer2],
        }
