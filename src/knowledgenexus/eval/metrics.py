"""IR metrics for eval (Hit@k, MRR, gap)."""

from __future__ import annotations

from knowledgenexus.eval.models import CaseLayerResult, LayerMetrics


def hit_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> bool:
    if not relevant_ids:
        return False
    return bool(set(retrieved_ids[:k]) & relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    if not relevant_ids:
        return 0.0
    for rank, item_id in enumerate(retrieved_ids, start=1):
        if item_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def score_case(
    case_id: str,
    retrieved_ids: list[str],
    relevant_ids: set[str],
    *,
    planned_query: str | None = None,
) -> CaseLayerResult:
    return CaseLayerResult(
        case_id=case_id,
        hit_at_5=hit_at_k(retrieved_ids, relevant_ids, 5),
        hit_at_10=hit_at_k(retrieved_ids, relevant_ids, 10),
        mrr=reciprocal_rank(retrieved_ids, relevant_ids),
        retrieved_ids=list(retrieved_ids),
        planned_query=planned_query,
    )


def aggregate(results: list[CaseLayerResult], *, n_skipped: int = 0) -> LayerMetrics:
    n = len(results)
    if n == 0:
        return LayerMetrics(
            hit_at_5=0.0,
            hit_at_10=0.0,
            mrr=0.0,
            n_cases=0,
            n_skipped=n_skipped,
        )
    return LayerMetrics(
        hit_at_5=sum(1 for r in results if r.hit_at_5) / n,
        hit_at_10=sum(1 for r in results if r.hit_at_10) / n,
        mrr=sum(r.mrr for r in results) / n,
        n_cases=n,
        n_skipped=n_skipped,
    )


def compute_gap(layer1: LayerMetrics | None, layer2: LayerMetrics | None) -> dict[str, float] | None:
    if layer1 is None or layer2 is None:
        return None
    return {
        "hit_at_5": layer1.hit_at_5 - layer2.hit_at_5,
        "hit_at_10": layer1.hit_at_10 - layer2.hit_at_10,
        "mrr": layer1.mrr - layer2.mrr,
    }
