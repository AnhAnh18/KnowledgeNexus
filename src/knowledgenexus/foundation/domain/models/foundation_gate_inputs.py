"""Sanitized inputs accepted by the external Foundation gate evaluators.

These records intentionally contain no page text, URLs, credentials, or raw
processor payloads.  They are the narrow boundary between a local run and a
committable F4/F7 gate result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_MEDIA_ID = re.compile(r"\Aconfluence:attachment:(?:att)?[0-9]+\Z")
_DATASET_VERSION = re.compile(r"\Av[0-9]{8}-[0-9]{6}-[0-9]{6}Z\Z")
_IDENTITY = re.compile(r"\A[a-z0-9][a-z0-9._:-]{0,127}\Z")
_MEDIA_KINDS = frozenset({
    "chart_screenshot", "digital_pdf", "drawio", "image", "image_only_pdf",
})
_MEDIA_STATUSES = frozenset({"processed", "skipped", "failed"})
_STREAMS = frozenset({
    "acl", "chunks", "documents", "media_assets", "relations", "symbols",
    "sync_state", "tombstones",
})


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


@dataclass(frozen=True, repr=False)
class SanitizedMediaProcessorOutcome:
    """One processor outcome with only stable, non-content evidence."""

    media_id: str
    kind: str
    status: str
    result_digest: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.media_id) is not str or _MEDIA_ID.fullmatch(self.media_id) is None:
            raise ValueError("media_id is invalid")
        if type(self.kind) is not str or self.kind not in _MEDIA_KINDS:
            raise ValueError("media kind is invalid")
        if type(self.status) is not str or self.status not in _MEDIA_STATUSES:
            raise ValueError("media status is invalid")
        _digest(self.result_digest, "result_digest")
        if self.reason_code is not None and (
            type(self.reason_code) is not str
            or _IDENTITY.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code is invalid")
        if self.status == "failed" and self.reason_code is None:
            raise ValueError("failed outcome requires reason_code")
        if self.status != "failed" and self.reason_code is not None:
            raise ValueError("successful outcome carries reason_code")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(media_id={self.media_id!r}, status={self.status!r})"


@dataclass(frozen=True, repr=False)
class SanitizedMediaProcessorRun:
    """A complete, bounded processor pass represented by sanitized facts."""

    outcomes: tuple[SanitizedMediaProcessorOutcome, ...]
    expected_media_ids: tuple[str, ...]
    source_digest_before: str
    source_digest_after: str
    write_digest_before: str
    write_digest_after: str

    def __post_init__(self) -> None:
        if type(self.outcomes) is not tuple:
            raise TypeError("outcomes are invalid")
        if type(self.expected_media_ids) is not tuple:
            raise TypeError("expected_media_ids are invalid")
        for outcome in self.outcomes:
            if type(outcome) is not SanitizedMediaProcessorOutcome:
                raise TypeError("outcomes are invalid")
        ids = tuple(outcome.media_id for outcome in self.outcomes)
        expected = self.expected_media_ids
        if (
            any(type(value) is not str or _MEDIA_ID.fullmatch(value) is None for value in expected)
            or tuple(sorted(expected)) != expected
            or len(set(expected)) != len(expected)
            or tuple(sorted(ids)) != ids
            or len(set(ids)) != len(ids)
            or set(ids) != set(expected)
        ):
            raise ValueError("media outcome identity or ordering is invalid")
        for field in (
            "source_digest_before", "source_digest_after",
            "write_digest_before", "write_digest_after",
        ):
            _digest(getattr(self, field), field)

    @property
    def source_unchanged(self) -> bool:
        return self.source_digest_before == self.source_digest_after

    @property
    def writes_unchanged(self) -> bool:
        return self.write_digest_before == self.write_digest_after

    def canonical_facts(self) -> tuple[tuple[str, str, str, str | None], ...]:
        return tuple(
            (item.media_id, item.kind, item.status, item.reason_code)
            for item in self.outcomes
        )

    @classmethod
    def from_batch(
        cls,
        *,
        batch_result: object,
        kind_by_media_id: tuple[tuple[str, str], ...],
        expected_media_ids: tuple[str, ...],
        source_digest_before: str,
        source_digest_after: str,
        write_digest_before: str,
        write_digest_after: str,
        skipped_media_ids: tuple[str, ...] = (),
    ) -> "SanitizedMediaProcessorRun":
        """Sanitize a trusted ``MediaBatchProcessingResult`` without copying text.

        The exact batch type is checked before reading any attributes.  Only
        media IDs, processing status, failure category, and asset content hash
        are retained in the resulting gate input.
        """
        from knowledgenexus.foundation.application.use_cases.process_confluence_media_batch import (
            MediaBatchProcessingResult,
        )

        if type(batch_result) is not MediaBatchProcessingResult:
            raise TypeError("batch_result is invalid")
        if type(kind_by_media_id) is not tuple or type(expected_media_ids) is not tuple or type(skipped_media_ids) is not tuple:
            raise TypeError("media scope is invalid")
        kinds = dict(kind_by_media_id)
        if len(kinds) != len(kind_by_media_id):
            raise ValueError("duplicate media kind mapping")
        skipped = set(skipped_media_ids)
        if any(type(value) is not str for value in skipped):
            raise TypeError("skipped media IDs are invalid")
        expected = tuple(expected_media_ids)
        assets = batch_result.assets
        if type(assets) is not tuple:
            raise TypeError("batch assets are invalid")
        outcomes: list[SanitizedMediaProcessorOutcome] = []
        for asset in assets:
            if type(asset) is not dict:
                raise ValueError("batch asset is invalid")
            media_id = asset.get("media_id")
            if type(media_id) is not str or media_id not in kinds:
                raise ValueError("batch asset identity is invalid")
            status = "skipped" if media_id in skipped else (
                "failed" if asset.get("processing_status") == "failed" else "processed"
            )
            failure = "processor_failure" if status == "failed" else None
            result_digest = asset.get("content_hash")
            outcomes.append(
                SanitizedMediaProcessorOutcome(
                    media_id=media_id,
                    kind=kinds[media_id],
                    status=status,
                    result_digest=result_digest,
                    reason_code=failure,
                )
            )
        return cls(
            outcomes=tuple(sorted(outcomes, key=lambda item: item.media_id)),
            expected_media_ids=expected,
            source_digest_before=source_digest_before,
            source_digest_after=source_digest_after,
            write_digest_before=write_digest_before,
            write_digest_after=write_digest_after,
        )


@dataclass(frozen=True, repr=False)
class BoundedMediaGateRequest:
    """Input for :class:`EvaluateBoundedMediaCorpusAcceptance`."""

    first_run: SanitizedMediaProcessorRun
    second_run: SanitizedMediaProcessorRun
    evidence_kind: str

    def __post_init__(self) -> None:
        if type(self.first_run) is not SanitizedMediaProcessorRun or type(self.second_run) is not SanitizedMediaProcessorRun:
            raise TypeError("media runs are invalid")
        if type(self.evidence_kind) is not str or self.evidence_kind not in {"synthetic_fixture", "sanitized_real_capture"}:
            raise ValueError("evidence_kind is invalid")
        if self.first_run.expected_media_ids != self.second_run.expected_media_ids:
            raise ValueError("media run scopes differ")


@dataclass(frozen=True, repr=False)
class PublishedSnapshotReadback:
    """Sanitized readback metadata for one published snapshot."""

    dataset_version: str
    content_digest: str
    observed_pages: int
    stream_counts: tuple[tuple[str, int], ...]
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

    def __post_init__(self) -> None:
        if type(self.dataset_version) is not str or _DATASET_VERSION.fullmatch(self.dataset_version) is None:
            raise ValueError("dataset_version is invalid")
        _digest(self.content_digest, "content_digest")
        if type(self.observed_pages) is not int or self.observed_pages < 0:
            raise ValueError("observed_pages is invalid")
        if type(self.stream_counts) is not tuple:
            raise TypeError("stream_counts are invalid")
        previous: str | None = None
        seen: set[str] = set()
        for item in self.stream_counts:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("stream_counts are invalid")
            stream, count = item
            if type(stream) is not str or stream not in _STREAMS or stream in seen or (previous is not None and stream <= previous):
                raise ValueError("stream_counts ordering is invalid")
            if type(count) is not int or count < 0:
                raise ValueError("stream count is invalid")
            previous = stream
            seen.add(stream)
        if seen != _STREAMS:
            raise ValueError("stream_counts must cover all Foundation streams")
        for field in (
            "readback_valid", "relation_closed", "acl_closed", "sync_closed",
            "atomic_publish", "no_clobber", "sanitized_output",
        ):
            if type(getattr(self, field)) is not bool:
                raise TypeError(f"{field} is invalid")
        if self.transport not in {"offline_fixture", "production"}:
            raise ValueError("transport is invalid")
        for field in ("rss_baseline_bytes", "rss_peak_bytes", "duration_milliseconds"):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field} is invalid")
        if self.rss_peak_bytes is not None and self.rss_baseline_bytes is not None and self.rss_peak_bytes < self.rss_baseline_bytes:
            raise ValueError("RSS counters are inconsistent")

    def canonical_facts(self) -> tuple[object, ...]:
        return (
            self.dataset_version, self.content_digest, self.observed_pages,
            self.stream_counts, self.readback_valid, self.relation_closed,
            self.acl_closed, self.sync_closed, self.atomic_publish,
            self.no_clobber, self.sanitized_output, self.transport,
            self.rss_baseline_bytes, self.rss_peak_bytes,
            self.duration_milliseconds,
        )


@dataclass(frozen=True, repr=False)
class ScaleGateRequest:
    """Input for :class:`EvaluateScaleGateEvidence`."""

    profile_id: str
    target_pages: int
    first_readback: PublishedSnapshotReadback
    second_readback: PublishedSnapshotReadback
    evidence_kind: str

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str or self.profile_id not in {"m7-crawl-scale-acceptance-v2", "m7-crawl-reliability-v1"}:
            raise ValueError("profile_id is invalid")
        if type(self.target_pages) is not int or self.target_pages not in (10000, 100000):
            raise ValueError("target_pages is invalid")
        if self.profile_id == "m7-crawl-reliability-v1" and self.target_pages != 10000:
            raise ValueError("reliability profile cannot claim 100k target")
        if type(self.first_readback) is not PublishedSnapshotReadback or type(self.second_readback) is not PublishedSnapshotReadback:
            raise TypeError("readback metadata is invalid")
        if type(self.evidence_kind) is not str or self.evidence_kind not in {"synthetic_fixture", "sanitized_real_capture"}:
            raise ValueError("evidence_kind is invalid")


__all__ = [
    "SanitizedMediaProcessorOutcome", "SanitizedMediaProcessorRun",
    "BoundedMediaGateRequest", "PublishedSnapshotReadback", "ScaleGateRequest",
]
