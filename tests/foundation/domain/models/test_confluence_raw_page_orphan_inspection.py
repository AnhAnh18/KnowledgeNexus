from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionDecision,
    ConfluenceRawPageOrphanInspectionRequest,
    ConfluenceRawPageOrphanInspectionResult,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")
OTHER_RUN_ID = CrawlRunId("87654321-4321-4234-9234-cba987654321")


def _request(
    *,
    run_id: CrawlRunId = RUN_ID,
    generation_id: CrawlRunId = RUN_ID,
    page_id: str = "1000",
    source_version: str | None = "v1",
) -> ConfluenceRawPageOrphanInspectionRequest:
    return ConfluenceRawPageOrphanInspectionRequest.capture(
        run_id=run_id,
        generation_id=generation_id,
        page_id=page_id,
        source_version=source_version,
    )


def test_request_binds_fixed_profile_and_generation() -> None:
    request = _request(source_version=None)

    assert request.request_profile_version == "m7-confluence-request-profile-v1"
    assert request.generation_id == RUN_ID
    assert request.source_version is None
    assert repr(request) == "ConfluenceRawPageOrphanInspectionRequest()"

    with pytest.raises(ValueError):
        _request(generation_id=OTHER_RUN_ID)
    with pytest.raises(ValueError):
        _request(page_id="../escape")
    with pytest.raises(ValueError):
        ConfluenceRawPageOrphanInspectionRequest.capture(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            page_id="1000",
            source_version=None,
            request_profile_version="other",
        )


def test_result_decisions_and_repr_are_sanitized() -> None:
    envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID,
        page_id="1000",
        source_version="secret-source-version",
        http_status=200,
        body_bytes=b"private body",
    )
    result = ConfluenceRawPageOrphanInspectionResult(
        decision=ConfluenceRawPageOrphanInspectionDecision.REPLAYABLE,
        envelope=envelope,
    )

    assert result.envelope == envelope
    assert "private body" not in repr(result)
    assert str(RUN_ID) not in repr(result)
    assert "secret-source-version" not in repr(result)

    for decision in ConfluenceRawPageOrphanInspectionDecision:
        if decision is ConfluenceRawPageOrphanInspectionDecision.REPLAYABLE:
            continue
        assert ConfluenceRawPageOrphanInspectionResult(decision=decision).decision is decision

    with pytest.raises(ValueError):
        ConfluenceRawPageOrphanInspectionResult(
            decision=ConfluenceRawPageOrphanInspectionDecision.MISSING,
            envelope=envelope,
        )
