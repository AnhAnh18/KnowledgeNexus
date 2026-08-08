"""Evaluate the sanitized external-input gates for Foundation F4 and F7."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from knowledgenexus.foundation.domain.models.foundation_gate import (
    BoundedMediaCorpusAcceptance,
    ScaleGateEvidence,
)
from knowledgenexus.foundation.domain.models.foundation_gate_inputs import (
    BoundedMediaGateRequest,
    PublishedSnapshotReadback,
    SanitizedMediaProcessorRun,
    ScaleGateRequest,
)


class FoundationGateEvaluationError(ValueError):
    """Malformed sanitized gate input; no source/runtime details are retained."""


def _digest_facts(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        raise FoundationGateEvaluationError("gate facts are not serializable") from None
    return hashlib.sha256(encoded).hexdigest()


def _media_counts(run: SanitizedMediaProcessorRun) -> tuple[tuple[str, int], ...]:
    counts = Counter(item.kind for item in run.outcomes)
    return tuple(sorted((kind, count) for kind, count in counts.items()))


def _media_failure_reason(
    request: BoundedMediaGateRequest,
    *,
    counts: tuple[tuple[str, int], ...],
) -> str | None:
    first, second = request.first_run, request.second_run
    reasons: list[str] = []
    if first.canonical_facts() != second.canonical_facts():
        reasons.append("nondeterministic_repeat")
    if not first.source_unchanged or not second.source_unchanged:
        reasons.append("source_changed")
    if not first.writes_unchanged or not second.writes_unchanged:
        reasons.append("writes_changed")
    if sum(item.status == "failed" for item in first.outcomes) or sum(item.status == "failed" for item in second.outcomes):
        reasons.append("processor_failure")
    if {kind for kind, _ in counts} != {"chart_screenshot", "digital_pdf", "drawio", "image", "image_only_pdf"}:
        reasons.append("corpus_coverage_incomplete")
    return ";".join(reasons) if reasons else None


class EvaluateBoundedMediaCorpusAcceptance:
    """Turn two bounded, sanitized media passes into the F4 gate record."""

    def execute(self, *, request: object) -> BoundedMediaCorpusAcceptance:
        if type(request) is not BoundedMediaGateRequest:
            raise FoundationGateEvaluationError("request is invalid")
        first, second = request.first_run, request.second_run
        # The request model has already rejected duplicate/omitted identities;
        # repeat facts are compared before any status-derived aggregation.
        counts = _media_counts(first)
        processed = sum(item.status == "processed" for item in first.outcomes)
        skipped = sum(item.status == "skipped" for item in first.outcomes)
        failed = sum(item.status == "failed" for item in first.outcomes)
        reason = _media_failure_reason(request, counts=counts)
        facts = {
            "evidence_kind": request.evidence_kind,
            "expected_media_ids": first.expected_media_ids,
            "first": first.canonical_facts(),
            "second": second.canonical_facts(),
            "source": (
                first.source_digest_before, first.source_digest_after,
                second.source_digest_before, second.source_digest_after,
            ),
            "writes": (
                first.write_digest_before, first.write_digest_after,
                second.write_digest_before, second.write_digest_after,
            ),
        }
        if reason is not None:
            return BoundedMediaCorpusAcceptance(
                status="failed",
                evidence_kind=request.evidence_kind,
                kind_counts=counts,
                processed_count=processed,
                skipped_count=skipped,
                failed_count=failed,
                deterministic_repeat=first.canonical_facts() == second.canonical_facts(),
                source_unchanged=first.source_unchanged and second.source_unchanged,
                no_silent_omission=True,
                evidence_digest=None,
                failure_reason=reason,
            )
        return BoundedMediaCorpusAcceptance(
            status="complete",
            evidence_kind=request.evidence_kind,
            kind_counts=counts,
            processed_count=processed,
            skipped_count=skipped,
            failed_count=failed,
            deterministic_repeat=True,
            source_unchanged=True,
            no_silent_omission=True,
            evidence_digest=_digest_facts(facts),
        )


def _scale_failure_reason(request: ScaleGateRequest) -> str | None:
    first, second = request.first_readback, request.second_readback
    reasons: list[str] = []
    if first.content_digest != second.content_digest:
        reasons.append("nondeterministic_repeat")
    for label, value in (
        ("first_readback", first.readback_valid),
        ("second_readback", second.readback_valid),
        ("relation_closure", first.relation_closed and second.relation_closed),
        ("acl_closure", first.acl_closed and second.acl_closed),
        ("sync_closure", first.sync_closed and second.sync_closed),
        ("atomic_publish", first.atomic_publish and second.atomic_publish),
        ("no_clobber", first.no_clobber and second.no_clobber),
        ("sanitized_output", first.sanitized_output and second.sanitized_output),
    ):
        if not value:
            reasons.append(label)
    if first.stream_counts != second.stream_counts:
        reasons.append("stream_counts_differ")
    if first.transport != second.transport:
        reasons.append("transport_differs")
    if request.evidence_kind == "sanitized_real_capture" and (
        first.transport != "production" or second.transport != "production"
    ):
        reasons.append("real_evidence_requires_production_transport")
    if first.observed_pages < request.target_pages or second.observed_pages < request.target_pages:
        reasons.append("target_pages_unmet")
    return ";".join(reasons) if reasons else None


class EvaluateScaleGateEvidence:
    """Evaluate two published snapshot readbacks for F5/F7 scale evidence."""

    def execute(self, *, request: object) -> ScaleGateEvidence:
        if type(request) is not ScaleGateRequest:
            raise FoundationGateEvaluationError("request is invalid")
        first, second = request.first_readback, request.second_readback
        reason = _scale_failure_reason(request)
        facts = {
            "profile_id": request.profile_id,
            "target_pages": request.target_pages,
            "evidence_kind": request.evidence_kind,
            "first": first.canonical_facts(),
            "second": second.canonical_facts(),
        }
        common = dict(
            profile_id=request.profile_id,
            target_pages=request.target_pages,
            observed_pages=min(first.observed_pages, second.observed_pages),
            run_count=2,
            stream_counts=first.stream_counts,
            deterministic_repeat=first.content_digest == second.content_digest,
            readback_valid=first.readback_valid and second.readback_valid,
            relation_closed=first.relation_closed and second.relation_closed,
            acl_closed=first.acl_closed and second.acl_closed,
            sync_closed=first.sync_closed and second.sync_closed,
            atomic_publish=first.atomic_publish and second.atomic_publish,
            no_clobber=first.no_clobber and second.no_clobber,
            sanitized_output=first.sanitized_output and second.sanitized_output,
            transport=first.transport if first.transport == second.transport else "offline_fixture",
            rss_baseline_bytes=min(
                value for value in (first.rss_baseline_bytes, second.rss_baseline_bytes)
                if value is not None
            ) if first.rss_baseline_bytes is not None and second.rss_baseline_bytes is not None else None,
            rss_peak_bytes=max(
                value for value in (first.rss_peak_bytes, second.rss_peak_bytes)
                if value is not None
            ) if first.rss_peak_bytes is not None and second.rss_peak_bytes is not None else None,
            duration_milliseconds=max(
                value for value in (first.duration_milliseconds, second.duration_milliseconds)
                if value is not None
            ) if first.duration_milliseconds is not None and second.duration_milliseconds is not None else None,
            evidence_kind=request.evidence_kind,
        )
        if reason is not None:
            return ScaleGateEvidence(status="failed", **common, failure_reason=reason)
        return ScaleGateEvidence(
            status="pass", **common, evidence_digest=_digest_facts(facts)
        )


# Descriptive aliases for callers that prefer imperative use-case names.
EvaluateBoundedMediaGate = EvaluateBoundedMediaCorpusAcceptance
EvaluateScaleGate = EvaluateScaleGateEvidence


__all__ = [
    "FoundationGateEvaluationError",
    "EvaluateBoundedMediaCorpusAcceptance",
    "EvaluateBoundedMediaGate",
    "EvaluateScaleGateEvidence",
    "EvaluateScaleGate",
    "BoundedMediaGateRequest",
    "PublishedSnapshotReadback",
    "SanitizedMediaProcessorRun",
    "ScaleGateRequest",
]
