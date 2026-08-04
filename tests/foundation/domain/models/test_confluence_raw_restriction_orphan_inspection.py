from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_orphan_inspection import (
    ConfluenceRawRestrictionOrphanInspectionDecision as Decision,
    ConfluenceRawRestrictionOrphanInspectionError,
    ConfluenceRawRestrictionOrphanInspectionFailureCategory as FailureCategory,
    ConfluenceRawRestrictionOrphanInspectionRequest,
    ConfluenceRawRestrictionOrphanInspectionResult,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")


def _request(
    *,
    run_id: CrawlRunId = RUN_ID,
    selected_page_id: str = "1000",
    target_page_id: str = "1001",
) -> ConfluenceRawRestrictionOrphanInspectionRequest:
    return ConfluenceRawRestrictionOrphanInspectionRequest.capture(
        run_id=run_id,
        selected_page_id=selected_page_id,
        target_page_id=target_page_id,
    )


def test_request_binds_fixed_profile_and_strict_ids() -> None:
    request = _request()

    assert request.request_profile_version == M7_RESTRICTION_REQUEST_PROFILE_VERSION
    assert repr(request) == "ConfluenceRawRestrictionOrphanInspectionRequest()"

    with pytest.raises(ValueError):
        _request(selected_page_id="../escape")
    with pytest.raises(ValueError):
        _request(target_page_id="1001.json")
    with pytest.raises(ValueError):
        ConfluenceRawRestrictionOrphanInspectionRequest.capture(
            run_id=RUN_ID,
            selected_page_id="1000",
            target_page_id="1001",
            request_profile_version="other",
        )


def test_error_and_result_are_sanitized() -> None:
    error = ConfluenceRawRestrictionOrphanInspectionError(
        FailureCategory.INSPECTION_FAILED
    )
    assert str(error) == "inspection_failed"
    assert repr(error) == "ConfluenceRawRestrictionOrphanInspectionError('inspection_failed')"

    envelope = ConfluenceRestrictionEvidenceEnvelope.capture(
        request_profile_version=M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        selected_page_id="1000",
        target_page_id="1001",
        http_status=200,
        body_bytes=b"secret body",
    )
    result = ConfluenceRawRestrictionOrphanInspectionResult(
        decision=Decision.REPLAYABLE,
        envelope=envelope,
    )
    assert result.envelope == envelope
    assert "secret body" not in repr(result)
    assert "1000" not in repr(result)
    assert "1001" not in repr(result)

    for decision in Decision:
        if decision is Decision.REPLAYABLE:
            continue
        assert ConfluenceRawRestrictionOrphanInspectionResult(
            decision=decision
        ).decision is decision

    with pytest.raises(ValueError):
        ConfluenceRawRestrictionOrphanInspectionResult(
            decision=Decision.MISSING,
            envelope=envelope,
        )
