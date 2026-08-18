"""Load and validate golden query JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.models import GoldenCase


class GoldenLoadError(ValueError):
    """Invalid golden file or case."""


def load_golden_cases(path: Path | str) -> list[GoldenCase]:
    file_path = Path(path)
    if not file_path.is_file():
        raise GoldenLoadError(f"Golden file not found: {file_path}")

    cases: list[GoldenCase] = []
    with file_path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                raise GoldenLoadError(f"{file_path}:{line_no}: invalid JSON ({e})") from e
            cases.append(_parse_case(payload, file_path, line_no))
    if not cases:
        raise GoldenLoadError(f"No golden cases in {file_path}")
    return cases


def _parse_case(payload: dict[str, Any], path: Path, line_no: int) -> GoldenCase:
    required = ("id", "user_question", "search_query")
    for key in required:
        if key not in payload or not str(payload[key]).strip():
            raise GoldenLoadError(f"{path}:{line_no}: missing or empty '{key}'")

    chunk_ids = tuple(str(x) for x in payload.get("relevant_chunk_ids") or [])
    doc_ids = tuple(str(x) for x in payload.get("relevant_document_ids") or [])
    source_ids = tuple(str(x) for x in payload.get("relevant_source_ids") or [])
    if not chunk_ids and not doc_ids and not source_ids:
        raise GoldenLoadError(
            f"{path}:{line_no}: need relevant_chunk_ids, relevant_document_ids, "
            "and/or relevant_source_ids"
        )

    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise GoldenLoadError(f"{path}:{line_no}: filters must be an object")

    tags = tuple(str(t) for t in payload.get("tags") or [])
    source = str(payload.get("source") or "manual")

    return GoldenCase(
        id=str(payload["id"]),
        user_question=str(payload["user_question"]).strip(),
        search_query=str(payload["search_query"]).strip(),
        relevant_chunk_ids=chunk_ids,
        relevant_document_ids=doc_ids,
        relevant_source_ids=source_ids,
        filters=dict(filters),
        tags=tags,
        source=source,
    )
