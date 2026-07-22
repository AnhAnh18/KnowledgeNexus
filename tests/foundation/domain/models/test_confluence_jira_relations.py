from __future__ import annotations

from knowledgenexus.foundation.domain.models import (
    ConfluenceJiraRelationResult,
    JiraRelationQualityObservation,
)


def test_result_recursively_isolates_input_ownership_and_hides_repr() -> None:
    canonical = {
        "jira_keys": ["SENSITIVE-1"],
        "metadata": {"nested": ["original"]},
    }
    chunks = ({"jira_keys": ["SENSITIVE-1"], "heading_path": ["H"]},)
    relations = ({"relation_id": "rel:0000000000000000"},)
    metrics = {"nested": {"values": [1]}}
    observation = JiraRelationQualityObservation(
        unique_key_like_candidates=("SENSITIVE-1",),
        allowlisted_keys=("SENSITIVE-1",),
        outside_allowlist_keys=(),
    )

    result = ConfluenceJiraRelationResult(
        enriched_canonical_document=canonical,
        enriched_chunks=chunks,
        relations=relations,
        quality_observation=observation,
        metrics=metrics,
    )
    canonical["jira_keys"].append("LATE")
    canonical["metadata"]["nested"].append("late")  # type: ignore[index]
    chunks[0]["heading_path"].append("late")  # type: ignore[union-attr]
    metrics["nested"]["values"].append(2)  # type: ignore[index]

    assert result.enriched_canonical_document["jira_keys"] == ["SENSITIVE-1"]
    assert result.enriched_canonical_document["metadata"] == {
        "nested": ["original"]
    }
    assert result.enriched_chunks[0]["heading_path"] == ["H"]
    assert result.metrics == {"nested": {"values": [1]}}
    assert "SENSITIVE" not in repr(result)
    assert "SENSITIVE" not in repr(observation)


def test_result_is_ownership_isolated_not_deeply_immutable() -> None:
    result = ConfluenceJiraRelationResult(
        enriched_canonical_document={"jira_keys": []},
        enriched_chunks=(),
        relations=(),
        quality_observation=JiraRelationQualityObservation((), (), ()),
        metrics={},
    )

    result.enriched_canonical_document["jira_keys"].append("caller-owned")  # type: ignore[union-attr]

    assert result.enriched_canonical_document["jira_keys"] == ["caller-owned"]
