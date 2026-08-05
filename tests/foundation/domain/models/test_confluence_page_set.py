from __future__ import annotations

import math

import pytest

from knowledgenexus.foundation.domain.models import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetRequest,
    ConfluencePageSetResult,
    ConfluencePageWorkItem,
    ConfluencePageSetError,
    ConfluencePageSetFailureCategory,
    CrawlRunId,
)


RUN_ID = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")


def _item(page_id: str = "1000") -> ConfluencePageWorkItem:
    return ConfluencePageWorkItem(page_id=page_id, crawled_at="2026-07-22T00:00:00Z")


def test_request_requires_nonempty_ordered_unique_tuple() -> None:
    with pytest.raises(ValueError):
        ConfluencePageSetRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=(),
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        )
    with pytest.raises(TypeError):
        ConfluencePageSetRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=[_item()],  # type: ignore[arg-type]
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        )
    with pytest.raises(ValueError):
        ConfluencePageSetRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=(_item(), _item()),
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        )


def test_metrics_reject_impossible_cross_counts() -> None:
    with pytest.raises(ValueError):
        ConfluencePageSetMetrics(
            requested_pages=2,
            succeeded_pages=1,
            failed_pages=0,
            document_count=1,
            chunk_count=0,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(),
        )
    with pytest.raises(ValueError):
        ConfluencePageSetPageMetrics(
            page_ordinal=1,
            chunk_count=1,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(),
        )


def test_result_rejects_nan_and_noncontiguous_page_metrics() -> None:
    metrics = ConfluencePageSetMetrics(
        requested_pages=1,
        succeeded_pages=1,
        failed_pages=0,
        document_count=1,
        chunk_count=0,
        warning_count=0,
        reference_intent_count=0,
        content_kind_counts=(),
    )
    page_metrics = (
        ConfluencePageSetPageMetrics(
            page_ordinal=1,
            chunk_count=0,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(),
        ),
    )
    with pytest.raises(TypeError):
        ConfluencePageSetResult(
            documents=({"value": math.nan},),
            chunks=(),
            page_metrics=page_metrics,
            metrics=metrics,
        )


def test_result_rejects_page_metric_aggregate_mismatch_and_error_ordinal() -> None:
    metrics = ConfluencePageSetMetrics(
        requested_pages=1,
        succeeded_pages=1,
        failed_pages=0,
        document_count=1,
        chunk_count=1,
        warning_count=0,
        reference_intent_count=0,
        content_kind_counts=(("prose", 1),),
    )
    page_metrics = (
        ConfluencePageSetPageMetrics(
            page_ordinal=1,
            chunk_count=0,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(),
        ),
    )
    with pytest.raises(ValueError):
        ConfluencePageSetResult(
            documents=({"document_id": "doc"},),
            chunks=({"chunk_id": "chunk"},),
            page_metrics=page_metrics,
            metrics=metrics,
        )
    with pytest.raises(ValueError):
        ConfluencePageSetError(
            ConfluencePageSetFailureCategory.INTERNAL_FAILURE,
            page_ordinal=2,
            requested_pages=1,
            succeeded_pages=0,
        )
