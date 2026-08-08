"""Runtime-validated aggregate gates for external Foundation evidence.

The records in this module deliberately contain only sanitized identities,
digests, counters, and booleans.  They are suitable for committing as an
operator handoff without carrying source URLs, page content, or credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from knowledgenexus.foundation.domain.models.media_ocr import OcrLimits


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_IDENTITY = re.compile(r"\A[a-z0-9][a-z0-9._:-]{0,127}\Z")
_RFC3339 = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)

_EVIDENCE_KINDS = frozenset({"synthetic_fixture", "sanitized_real_capture"})
_MEDIA_KINDS = (
    "chart_screenshot",
    "digital_pdf",
    "drawio",
    "image",
    "image_only_pdf",
)
_MEDIA_KIND_SET = frozenset(_MEDIA_KINDS)
_STREAMS = (
    "acl",
    "chunks",
    "documents",
    "media_assets",
    "relations",
    "symbols",
    "sync_state",
    "tombstones",
)
_STREAM_SET = frozenset(_STREAMS)


def _optional_identity(value: object, field: str) -> None:
    if value is not None and (type(value) is not str or _IDENTITY.fullmatch(value) is None):
        raise ValueError(f"{field} is invalid")


def _digest(value: object, field: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")


def _bool(value: object, field: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field} is invalid")


@dataclass(frozen=True, repr=False)
class OcrEngineApproval:
    """M9-A4 approval record for an OCR runtime/model build.

    ``pending_external_input`` is intentionally a first-class state.  It
    cannot carry engine identities or output evidence, so callers cannot
    accidentally activate a guessed/default OCR engine.
    """

    status: str
    engine_id: str | None = None
    engine_version: str | None = None
    runtime_identity: str | None = None
    model_identity: str | None = None
    build_identity: str | None = None
    offline_only: bool | None = None
    limits: OcrLimits = OcrLimits()
    evidence_kind: str | None = None
    evidence_digest: str | None = None
    failure_reason: str | None = None
    approved_at: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"approved", "pending_external_input", "failed"}:
            raise ValueError("status is invalid")
        if type(self.limits) is not OcrLimits:
            raise TypeError("limits are invalid")
        for field in ("engine_id", "engine_version", "runtime_identity", "model_identity", "build_identity"):
            _optional_identity(getattr(self, field), field)
        if self.evidence_kind is not None and self.evidence_kind not in _EVIDENCE_KINDS:
            raise ValueError("evidence_kind is invalid")
        if self.failure_reason is not None and (type(self.failure_reason) is not str or not self.failure_reason or len(self.failure_reason) > 256):
            raise ValueError("failure_reason is invalid")
        if self.approved_at is not None and (type(self.approved_at) is not str or _RFC3339.fullmatch(self.approved_at) is None):
            raise ValueError("approved_at is invalid")
        if self.status == "approved":
            required = (self.engine_id, self.engine_version, self.runtime_identity, self.model_identity, self.build_identity, self.evidence_kind, self.evidence_digest, self.approved_at)
            if any(value is None for value in required) or self.offline_only is not True:
                raise ValueError("approved record is incomplete")
            if self.evidence_kind != "sanitized_real_capture":
                raise ValueError("approved OCR requires sanitized real evidence")
            _digest(self.evidence_digest, "evidence_digest")
            if self.failure_reason is not None:
                raise ValueError("approved record carries failure")
        elif self.status == "pending_external_input":
            if any(value is not None for value in (self.engine_id, self.engine_version, self.runtime_identity, self.model_identity, self.build_identity, self.offline_only, self.evidence_kind, self.evidence_digest, self.approved_at, self.failure_reason)):
                raise ValueError("pending record carries activation data")
        else:
            if self.failure_reason is None or any(value is not None for value in (self.evidence_digest, self.approved_at)):
                raise ValueError("failed record is invalid")
            if self.offline_only is not None and type(self.offline_only) is not bool:
                raise TypeError("offline_only is invalid")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r})"


@dataclass(frozen=True, repr=False)
class BoundedMediaCorpusAcceptance:
    """Sanitized acceptance summary for the bounded F4 media corpus."""

    status: str
    evidence_kind: str | None
    kind_counts: tuple[tuple[str, int], ...]
    processed_count: int
    skipped_count: int
    failed_count: int
    deterministic_repeat: bool
    source_unchanged: bool
    no_silent_omission: bool
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"complete", "pending_external_input", "failed"}:
            raise ValueError("status is invalid")
        if self.evidence_kind is not None and self.evidence_kind not in _EVIDENCE_KINDS:
            raise ValueError("evidence_kind is invalid")
        for field in ("processed_count", "skipped_count", "failed_count"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} is invalid")
        for field in ("deterministic_repeat", "source_unchanged", "no_silent_omission"):
            _bool(getattr(self, field), field)
        if type(self.kind_counts) is not tuple:
            raise TypeError("kind_counts is invalid")
        previous: str | None = None
        total = 0
        seen: set[str] = set()
        for kind, count in self.kind_counts:
            if type(kind) is not str or kind not in _MEDIA_KIND_SET or kind in seen:
                raise ValueError("kind_counts contains invalid media kind")
            if previous is not None and kind <= previous:
                raise ValueError("kind_counts ordering is invalid")
            if type(count) is not int or count < 0:
                raise ValueError("kind_counts count is invalid")
            previous, total = kind, total + count
            seen.add(kind)
        if total != self.processed_count + self.skipped_count + self.failed_count:
            raise ValueError("media counters are inconsistent")
        if self.status == "pending_external_input":
            if self.kind_counts or total or any((self.deterministic_repeat, self.source_unchanged, self.no_silent_omission)) or self.evidence_kind is not None or self.evidence_digest is not None:
                raise ValueError("pending media gate carries observations")
        elif self.status == "complete":
            if seen != _MEDIA_KIND_SET or any(count == 0 for _, count in self.kind_counts):
                raise ValueError("complete media gate lacks required corpus kinds")
            if self.failed_count != 0:
                raise ValueError("complete media gate contains failures")
            if not all((self.deterministic_repeat, self.source_unchanged, self.no_silent_omission)):
                raise ValueError("complete media gate checks are incomplete")
            if self.evidence_kind is None or self.evidence_digest is None:
                raise ValueError("complete media gate evidence is missing")
            _digest(self.evidence_digest, "evidence_digest")
        elif self.failed_count == 0 or not self.no_silent_omission:
            raise ValueError("failed media gate must report explicit failures")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r}, total={sum(count for _, count in self.kind_counts)})"


@dataclass(frozen=True, repr=False)
class ScaleGateEvidence:
    """Aggregate F5/F7 readback evidence without source/runtime data."""

    status: str
    profile_id: str
    target_pages: int
    observed_pages: int
    run_count: int
    stream_counts: tuple[tuple[str, int], ...]
    deterministic_repeat: bool
    readback_valid: bool
    relation_closed: bool
    acl_closed: bool
    sync_closed: bool
    atomic_publish: bool
    no_clobber: bool
    sanitized_output: bool
    transport: str
    rss_baseline_bytes: int | None = None
    rss_peak_bytes: int | None = None
    duration_milliseconds: int | None = None
    evidence_kind: str | None = None
    evidence_digest: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"pass", "pending_external_input", "failed"}:
            raise ValueError("status is invalid")
        if type(self.profile_id) is not str or self.profile_id not in {"m7-crawl-scale-acceptance-v2", "m7-crawl-reliability-v1"}:
            raise ValueError("profile_id is invalid")
        if self.target_pages not in (10000, 100000) or type(self.target_pages) is not int:
            raise ValueError("target_pages is invalid")
        if self.profile_id == "m7-crawl-reliability-v1" and self.target_pages != 10000:
            raise ValueError("reliability profile cannot claim 100k target")
        for field in ("observed_pages", "run_count"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} is invalid")
        if type(self.stream_counts) is not tuple:
            raise TypeError("stream_counts is invalid")
        previous: str | None = None
        seen: set[str] = set()
        for stream, count in self.stream_counts:
            if type(stream) is not str or stream not in _STREAM_SET or stream in seen or (previous is not None and stream <= previous):
                raise ValueError("stream_counts ordering is invalid")
            if type(count) is not int or count < 0:
                raise ValueError("stream count is invalid")
            previous, _ = stream, count
            seen.add(stream)
        for field in ("deterministic_repeat", "readback_valid", "relation_closed", "acl_closed", "sync_closed", "atomic_publish", "no_clobber", "sanitized_output"):
            _bool(getattr(self, field), field)
        if self.transport not in {"offline_fixture", "production"}:
            raise ValueError("transport is invalid")
        for field in ("rss_baseline_bytes", "rss_peak_bytes", "duration_milliseconds"):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field} is invalid")
        if self.rss_peak_bytes is not None and self.rss_baseline_bytes is not None and self.rss_peak_bytes < self.rss_baseline_bytes:
            raise ValueError("RSS counters are inconsistent")
        if self.evidence_kind is not None and self.evidence_kind not in _EVIDENCE_KINDS:
            raise ValueError("evidence_kind is invalid")
        if self.failure_reason is not None and (type(self.failure_reason) is not str or not self.failure_reason or len(self.failure_reason) > 256):
            raise ValueError("failure_reason is invalid")
        if self.status == "pending_external_input":
            if self.observed_pages or self.run_count or self.stream_counts or self.evidence_digest is not None or self.failure_reason is not None or any((self.deterministic_repeat, self.readback_valid, self.relation_closed, self.acl_closed, self.sync_closed, self.atomic_publish, self.no_clobber, self.sanitized_output)):
                raise ValueError("pending scale gate carries observations")
        elif self.status == "pass":
            if self.observed_pages < self.target_pages or self.run_count < 2 or seen != _STREAM_SET:
                raise ValueError("scale evidence is incomplete")
            if not all((self.deterministic_repeat, self.readback_valid, self.relation_closed, self.acl_closed, self.sync_closed, self.atomic_publish, self.no_clobber, self.sanitized_output)):
                raise ValueError("scale checks are incomplete")
            if self.evidence_kind is None or self.evidence_digest is None:
                raise ValueError("scale evidence digest is missing")
            _digest(self.evidence_digest, "evidence_digest")
        elif self.evidence_digest is not None or self.failure_reason is None:
            raise ValueError("failed scale gate carries invalid evidence")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r}, target_pages={self.target_pages})"


__all__ = ["OcrEngineApproval", "BoundedMediaCorpusAcceptance", "ScaleGateEvidence"]
