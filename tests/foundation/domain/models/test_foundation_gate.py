from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.foundation_gate import (
    BoundedMediaCorpusAcceptance,
    OcrEngineApproval,
    ScaleGateEvidence,
)


def test_ocr_engine_approval_requires_sanitized_identity_and_offline_policy() -> None:
    record = OcrEngineApproval(
        status="approved",
        engine_id="tesseract",
        engine_version="5.3",
        runtime_identity="python-3.12",
        model_identity="eng-fast",
        build_identity="build-20260808",
        offline_only=True,
        evidence_kind="sanitized_real_capture",
        evidence_digest="a" * 64,
        approved_at="2026-08-08T12:00:00Z",
    )
    assert record.status == "approved"
    with pytest.raises(ValueError):
        OcrEngineApproval(status="approved", engine_id="guess")
    with pytest.raises(ValueError):
        OcrEngineApproval(
            status="approved", engine_id="engine", engine_version="1",
            runtime_identity="runtime", model_identity="model", build_identity="build",
            offline_only=False, evidence_kind="sanitized_real_capture",
            evidence_digest="a" * 64, approved_at="2026-08-08T12:00:00Z",
        )
    with pytest.raises(ValueError):
        OcrEngineApproval(status="pending_external_input", engine_id="engine")
    with pytest.raises((TypeError, ValueError)):
        OcrEngineApproval(status="approved", limits=object())


def test_bounded_media_corpus_requires_every_kind_and_balanced_counters() -> None:
    kinds = (
        ("chart_screenshot", 1),
        ("digital_pdf", 1),
        ("drawio", 1),
        ("image", 2),
        ("image_only_pdf", 1),
    )
    result = BoundedMediaCorpusAcceptance(
        status="complete", evidence_kind="synthetic_fixture", kind_counts=kinds,
        processed_count=5, skipped_count=1, failed_count=0,
        deterministic_repeat=True, source_unchanged=True, no_silent_omission=True,
        evidence_digest="b" * 64,
    )
    assert result.processed_count == 5
    with pytest.raises(ValueError):
        BoundedMediaCorpusAcceptance(
            status="complete", evidence_kind="synthetic_fixture",
            kind_counts=(("drawio", 1),), processed_count=1, skipped_count=0, failed_count=0,
            deterministic_repeat=True, source_unchanged=True, no_silent_omission=True,
            evidence_digest="b" * 64,
        )
    with pytest.raises(ValueError):
        BoundedMediaCorpusAcceptance(
            status="complete", evidence_kind="synthetic_fixture", kind_counts=kinds,
            processed_count=99, skipped_count=0, failed_count=0,
            deterministic_repeat=True, source_unchanged=True, no_silent_omission=True,
            evidence_digest="b" * 64,
        )
    with pytest.raises(ValueError):
        BoundedMediaCorpusAcceptance(
            status="pending_external_input", evidence_kind="synthetic_fixture", kind_counts=(),
            processed_count=0, skipped_count=0, failed_count=0,
            deterministic_repeat=False, source_unchanged=False, no_silent_omission=False,
            evidence_digest=None,
        )


def test_scale_gate_requires_two_readback_runs_and_all_streams() -> None:
    streams = (
        ("acl", 1), ("chunks", 2), ("documents", 1), ("media_assets", 1),
        ("relations", 1), ("symbols", 1), ("sync_state", 1), ("tombstones", 0),
    )
    result = ScaleGateEvidence(
        status="pass", profile_id="m7-crawl-scale-acceptance-v2", target_pages=10000,
        observed_pages=10000, run_count=2, stream_counts=streams,
        deterministic_repeat=True, readback_valid=True, relation_closed=True,
        acl_closed=True, sync_closed=True, atomic_publish=True, no_clobber=True,
        sanitized_output=True, transport="offline_fixture", rss_baseline_bytes=10,
        rss_peak_bytes=20, duration_milliseconds=100, evidence_kind="synthetic_fixture",
        evidence_digest="c" * 64,
    )
    assert result.target_pages == 10000
    with pytest.raises(ValueError):
        ScaleGateEvidence(
            status="pass", profile_id="m7-crawl-scale-acceptance-v2", target_pages=10000,
            observed_pages=10000, run_count=1, stream_counts=streams,
            deterministic_repeat=True, readback_valid=True, relation_closed=True,
            acl_closed=True, sync_closed=True, atomic_publish=True, no_clobber=True,
            sanitized_output=True, transport="offline_fixture", evidence_kind="synthetic_fixture",
            evidence_digest="c" * 64,
        )
    with pytest.raises(ValueError):
        ScaleGateEvidence(
            status="pending_external_input", profile_id="m7-crawl-scale-acceptance-v2",
            target_pages=10000, observed_pages=1, run_count=0, stream_counts=(),
            deterministic_repeat=False, readback_valid=False, relation_closed=False,
            acl_closed=False, sync_closed=False, atomic_publish=False, no_clobber=False,
            sanitized_output=False, transport="offline_fixture",
        )
    with pytest.raises(ValueError):
        ScaleGateEvidence(
            status="pass", profile_id="m7-crawl-reliability-v1", target_pages=100000,
            observed_pages=100000, run_count=2, stream_counts=streams,
            deterministic_repeat=True, readback_valid=True, relation_closed=True,
            acl_closed=True, sync_closed=True, atomic_publish=True, no_clobber=True,
            sanitized_output=True, transport="production", evidence_kind="sanitized_real_capture",
            evidence_digest="c" * 64,
        )
    with pytest.raises((TypeError, ValueError)):
        ScaleGateEvidence(status="pass", profile_id=object(), target_pages=10000,
                          observed_pages=10000, run_count=2, stream_counts=streams,
                          deterministic_repeat=True, readback_valid=True, relation_closed=True,
                          acl_closed=True, sync_closed=True, atomic_publish=True, no_clobber=True,
                          sanitized_output=True, transport="offline_fixture", evidence_kind="synthetic_fixture",
                          evidence_digest="c" * 64)
    with pytest.raises(ValueError):
        ScaleGateEvidence(
            status="pass", profile_id="m7-crawl-scale-acceptance-v2", target_pages=10000,
            observed_pages=10000, run_count=2, stream_counts=streams,
            deterministic_repeat=True, readback_valid=True, relation_closed=True,
            acl_closed=True, sync_closed=True, atomic_publish=True, no_clobber=True,
            sanitized_output=True, transport="offline_fixture",
            evidence_kind="sanitized_real_capture", evidence_digest="c" * 64,
        )
