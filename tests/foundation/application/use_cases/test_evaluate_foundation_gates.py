from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases.evaluate_foundation_gates import (
    FoundationGateEvaluationError,
    EvaluateBoundedMediaCorpusAcceptance,
    EvaluateScaleGateEvidence,
)
from knowledgenexus.foundation.domain.models.foundation_gate_inputs import (
    BoundedMediaGateRequest,
    PublishedSnapshotReadback,
    SanitizedMediaProcessorOutcome,
    SanitizedMediaProcessorRun,
    ScaleGateRequest,
)


def _media_run(*, source_after: str = "a" * 64, failed: bool = False) -> SanitizedMediaProcessorRun:
    kinds = ("chart_screenshot", "digital_pdf", "drawio", "image", "image_only_pdf")
    outcomes = tuple(
        SanitizedMediaProcessorOutcome(
            media_id=f"confluence:attachment:{index}",
            kind=kind,
            status="failed" if failed and index == 1003 else "processed",
            result_digest=chr(96 + index - 999) * 64,
            reason_code="capability_failure" if failed and index == 1003 else None,
        )
        for index, kind in zip(range(1000, 1005), kinds)
    )
    return SanitizedMediaProcessorRun(
        outcomes=outcomes,
        expected_media_ids=tuple(item.media_id for item in outcomes),
        source_digest_before="a" * 64,
        source_digest_after=source_after,
        write_digest_before="c" * 64,
        write_digest_after="c" * 64,
    )


def test_bounded_media_evaluator_derives_digest_and_requires_repeat() -> None:
    request = BoundedMediaGateRequest(
        first_run=_media_run(), second_run=_media_run(), evidence_kind="sanitized_real_capture"
    )
    result = EvaluateBoundedMediaCorpusAcceptance().execute(request=request)
    assert result.status == "complete"
    assert result.evidence_digest is not None
    assert result.processed_count == 5

    failed = EvaluateBoundedMediaCorpusAcceptance().execute(
        request=BoundedMediaGateRequest(
            first_run=_media_run(failed=True), second_run=_media_run(failed=True), evidence_kind="synthetic_fixture"
        )
    )
    assert failed.status == "failed"
    assert failed.failed_count == 1


@pytest.mark.parametrize("value", [None, object(), {"first_run": 1}])
def test_bounded_media_evaluator_rejects_wrong_runtime_types(value: object) -> None:
    with pytest.raises(FoundationGateEvaluationError):
        EvaluateBoundedMediaCorpusAcceptance().execute(request=value)


def _readback(*, digest: str = "d" * 64, closed: bool = True) -> PublishedSnapshotReadback:
    streams = (
        ("acl", 10), ("chunks", 20), ("documents", 10), ("media_assets", 3),
        ("relations", 4), ("symbols", 2), ("sync_state", 13), ("tombstones", 0),
    )
    return PublishedSnapshotReadback(
        dataset_version="v20260808-120000-000001Z",
        content_digest=digest,
        observed_pages=10000,
        stream_counts=streams,
        readback_valid=closed,
        relation_closed=closed,
        acl_closed=closed,
        sync_closed=closed,
        atomic_publish=closed,
        no_clobber=closed,
        sanitized_output=closed,
        transport="production",
        rss_baseline_bytes=100,
        rss_peak_bytes=200,
        duration_milliseconds=300,
    )


def test_scale_evaluator_accepts_repeat_readback_and_rejects_closure_failure() -> None:
    result = EvaluateScaleGateEvidence().execute(
        request=ScaleGateRequest(
            profile_id="m7-crawl-scale-acceptance-v2",
            target_pages=10000,
            first_readback=_readback(),
            second_readback=_readback(),
            evidence_kind="sanitized_real_capture",
        )
    )
    assert result.status == "pass"
    assert result.run_count == 2
    assert result.evidence_digest is not None

    failed = EvaluateScaleGateEvidence().execute(
        request=ScaleGateRequest(
            profile_id="m7-crawl-scale-acceptance-v2",
            target_pages=10000,
            first_readback=_readback(closed=False),
            second_readback=_readback(closed=False),
            evidence_kind="synthetic_fixture",
        )
    )
    assert failed.status == "failed"
    assert "readback" in (failed.failure_reason or "")


def test_gate_input_rejects_impossible_stream_counts_before_field_access() -> None:
    with pytest.raises(ValueError):
        _readback().__class__(
            dataset_version="v20260808-120000-000001Z",
            content_digest="d" * 64,
            observed_pages=10000,
            stream_counts=(("documents", True),),
            readback_valid=True,
            relation_closed=True,
            acl_closed=True,
            sync_closed=True,
            atomic_publish=True,
            no_clobber=True,
            sanitized_output=True,
            transport="production",
        )
