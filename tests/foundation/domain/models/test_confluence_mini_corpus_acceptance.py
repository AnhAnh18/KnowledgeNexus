from __future__ import annotations

import json

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_mini_corpus_acceptance import (
    MiniCorpusAcceptanceError,
    MiniCorpusAcceptanceFailureCategory,
    MiniCorpusAcceptanceRequest,
    MiniCorpusAcceptanceSummary,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageWorkItem,
)


RUN_ID = CrawlRunId("00000000-0000-4000-8000-000000000001")


def _request() -> MiniCorpusAcceptanceRequest:
    return MiniCorpusAcceptanceRequest(
        run_id=RUN_ID,
        generation_id=RUN_ID,
        items=tuple(
            ConfluencePageWorkItem(
                page_id=str(1000 + index),
                crawled_at="2026-08-05T00:00:00Z",
                expected_source_version="1",
            )
            for index in range(10)
        ),
    )


def _summary(**overrides: object) -> MiniCorpusAcceptanceSummary:
    values: dict[str, object] = {
        "status": "complete",
        "requested_pages": 10,
        "succeeded_pages": 10,
        "failed_pages": 0,
        "chunk_count": 20,
        "warning_count": 1,
        "reference_intent_count": 2,
        "content_kind_counts": (("prose", 18), ("table", 2)),
        "chunk_count_distribution": (1, 2, 4, 6),
        "token_count_distribution": (10, 20, 30, 40),
        "zero_chunk_pages": 0,
        "table_page_count": 1,
        "layout_page_count": 2,
        "reference_page_count": 1,
        "page_set_digest": "a" * 64,
        "chunk_stability_digest": "b" * 64,
        "first_page_set_digest": "a" * 64,
        "second_page_set_digest": "a" * 64,
        "first_chunk_stability_digest": "b" * 64,
        "second_chunk_stability_digest": "b" * 64,
        "tokenizer_asset_digest": "c" * 64,
        "profile_identity": "bge-m3:medium:chunker-1.2.0",
        "chunker_version": "1.2.0",
        "deterministic_repeat": True,
        "source_unchanged": True,
        "negative_pass": True,
        "no_writes": True,
        "report_leak_free": True,
        "distribution_labels": (
            ("chunk_count_distribution", "OBSERVED"),
            ("duration_milliseconds", "OBSERVED"),
            ("high_chunk_pages", "OBSERVED"),
            ("layout", "OBSERVED"),
            ("reference", "OBSERVED"),
            ("table", "OBSERVED"),
            ("token_count_distribution", "OBSERVED"),
            ("zero_chunk_pages", "NOT_APPLICABLE"),
        ),
        "ordinal_statuses": tuple((index, "succeeded", None) for index in range(1, 11)),
        "duration_milliseconds": 10,
    }
    values.update(overrides)
    return MiniCorpusAcceptanceSummary(**values)


def test_request_requires_bounded_unique_selection() -> None:
    request = _request()
    assert len(request.items) == 10
    with pytest.raises(ValueError):
        MiniCorpusAcceptanceRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=request.items[:9],
        )
    with pytest.raises(ValueError):
        MiniCorpusAcceptanceRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=request.items[:-1] + (request.items[0],),
        )


def test_summary_serialization_is_canonical_and_text_free() -> None:
    summary = _summary()
    encoded = summary.to_bytes()
    assert encoded == summary.to_bytes()
    assert json.loads(encoded)["status"] == "complete"
    assert b"page_id" not in encoded
    assert summary.digest() == summary.digest()


def test_summary_rejects_impossible_complete_counters() -> None:
    with pytest.raises(ValueError):
        _summary(failed_pages=1)
    with pytest.raises(ValueError):
        _summary(requested_pages=9, succeeded_pages=9, ordinal_statuses=tuple((index, "succeeded", None) for index in range(1, 10)))
    with pytest.raises(ValueError):
        _summary(chunk_count_distribution=(4, 1, 2, 5))
    with pytest.raises(ValueError):
        _summary(ordinal_statuses=((1, "failed", "raw_page_read_failed"),) + tuple((index, "succeeded", None) for index in range(2, 11)))
    with pytest.raises(ValueError):
        _summary(distribution_labels=(("bad", "OBSERVED"),) + _summary().distribution_labels[1:])


def test_summary_rejects_forbidden_aggregate_strings() -> None:
    with pytest.raises(ValueError):
        _summary(profile_identity="https://leak.example")
    with pytest.raises(ValueError):
        _summary(tokenizer_asset_digest="not-a-digest")
    with pytest.raises(ValueError):
        _summary(second_page_set_digest="d" * 64)
    with pytest.raises(ValueError):
        _summary(chunk_count_distribution=(0, 0, 0, 0))
    with pytest.raises(ValueError):
        _summary(chunk_count_distribution=(1, 1, 1, 1))
    with pytest.raises(ValueError):
        _summary(token_count_distribution=(0, 0, 0, 0))


def test_pending_summary_cannot_claim_acceptance() -> None:
    values = vars(_summary())
    values.update(
        status="pending_external_input",
        requested_pages=0,
        succeeded_pages=0,
        failed_pages=0,
        chunk_count=0,
        content_kind_counts=(),
        warning_count=0,
        reference_intent_count=0,
        zero_chunk_pages=0,
        table_page_count=0,
        layout_page_count=0,
        reference_page_count=0,
        chunk_count_distribution=(0, 0, 0, 0),
        token_count_distribution=(0, 0, 0, 0),
        distribution_labels=tuple((name, "NOT_APPLICABLE") for name, _ in _summary().distribution_labels),
        ordinal_statuses=(),
        duration_milliseconds=0,
        page_set_digest="0" * 64,
        chunk_stability_digest="0" * 64,
        first_page_set_digest="0" * 64,
        second_page_set_digest="0" * 64,
        first_chunk_stability_digest="0" * 64,
        second_chunk_stability_digest="0" * 64,
        tokenizer_asset_digest="0" * 64,
        deterministic_repeat=False,
        source_unchanged=False,
        negative_pass=False,
        no_writes=False,
        report_leak_free=False,
    )
    pending = MiniCorpusAcceptanceSummary(**values)
    assert pending.status == "pending_external_input"
    values["deterministic_repeat"] = True
    with pytest.raises(ValueError):
        MiniCorpusAcceptanceSummary(**values)


def test_public_boundary_rejects_malformed_runtime_values() -> None:
    with pytest.raises(TypeError):
        MiniCorpusAcceptanceRequest(run_id=object(), generation_id=object(), items=())
    with pytest.raises(TypeError):
        MiniCorpusAcceptanceError("processing_failed")
    with pytest.raises(TypeError):
        MiniCorpusAcceptanceSummary()
    with pytest.raises(TypeError):
        MiniCorpusAcceptanceSummary(**{**vars(_summary()), "page_id": "forbidden"})
    assert MiniCorpusAcceptanceFailureCategory.PROCESSING_FAILED.value == "processing_failed"
