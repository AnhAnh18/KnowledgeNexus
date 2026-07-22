from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_chunking import (
    ChunkingResult,
    ConfluenceChunkingError,
    ConfluenceChunkingFailureCategory,
)


def test_chunking_error_exposes_only_the_stable_category() -> None:
    error = ConfluenceChunkingError(
        ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE
    )

    assert str(error) == "unsplittable_code_line"
    assert error.category is ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE
    assert repr(error) == "ConfluenceChunkingError('unsplittable_code_line')"


def test_chunking_error_rejects_an_untyped_category() -> None:
    with pytest.raises(TypeError, match="category"):
        ConfluenceChunkingError("chunking_failed")  # type: ignore[arg-type]


def test_result_copies_records_and_nested_metrics() -> None:
    record = {"chunk_id": "chunk:confluence:0123456789abcdef"}
    by_kind = {"prose": 1}
    result = ChunkingResult(
        records=(record,),
        metrics={"chunks_total": 1, "chunks_by_kind": by_kind},
    )

    record["chunk_id"] = "mutated"
    by_kind["prose"] = 99

    assert result.records == (
        {"chunk_id": "chunk:confluence:0123456789abcdef"},
    )
    assert result.metrics == {
        "chunks_total": 1,
        "chunks_by_kind": {"prose": 1},
    }


def test_result_rejects_non_json_metrics() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        ChunkingResult(records=(), metrics={"bad": object()})
