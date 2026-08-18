"""Layer 1: oracle search_query → retrieve (no Skill)."""

from __future__ import annotations

from eval.config import EvalConfig
from eval.metrics import aggregate, score_case
from eval.models import CaseLayerResult, GoldenCase, LayerMetrics
from eval.retrieve import extract_ids, retrieve


def run_layer1(
    cases: list[GoldenCase],
    config: EvalConfig,
) -> tuple[LayerMetrics, list[CaseLayerResult]]:
    scored: list[CaseLayerResult] = []
    skipped = 0

    for case in cases:
        relevant = case.relevant_ids(config.match_on)
        if not relevant:
            skipped += 1
            continue

        result = retrieve(
            api_base_url=config.api_base_url,
            query=case.search_query,
            top_k=max(config.top_k, 10),
            score_threshold=config.score_threshold,
            filters=case.filters,
        )
        retrieved_ids = extract_ids(result, config.match_on)
        scored.append(
            score_case(
                case.id,
                retrieved_ids,
                relevant,
                planned_query=case.search_query,
            )
        )

    return aggregate(scored, n_skipped=skipped), scored
