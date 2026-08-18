"""Shared retrieve call + id extraction for both eval layers."""

from __future__ import annotations

from typing import Any

from eval.http_client import request_json
from eval.models import MatchOn


def retrieve(
    *,
    api_base_url: str,
    query: str,
    top_k: int,
    score_threshold: float = 0.0,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return request_json(
        "POST",
        api_base_url,
        "/api/v1/retrieve",
        data={
            "query": query,
            "top_k": top_k,
            "score_threshold": score_threshold,
            "filters": filters or {},
        },
    )


def extract_ids(result: dict[str, Any], match_on: MatchOn) -> list[str]:
    ids: list[str] = []
    for item in result.get("results") or []:
        citation = item.get("citation") or {}
        if match_on == "chunk_id":
            value = citation.get("chunk_id")
        elif match_on == "source_id":
            value = citation.get("source_id")
        else:
            value = citation.get("document_id")
        if value is not None:
            ids.append(str(value))
    return ids
