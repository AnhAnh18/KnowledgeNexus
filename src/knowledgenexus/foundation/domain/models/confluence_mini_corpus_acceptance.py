from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageWorkItem,
)
from knowledgenexus.foundation.domain.models.chunk_stability import ACTIVE_CHUNKER_VERSION


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_ZERO_DIGEST = "0" * 64
_CONTENT_KIND = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STATUSES = frozenset({"complete", "pending_external_input", "failed"})
_LABELS = frozenset({"PASS", "OBSERVED", "NOT_APPLICABLE"})
_LABEL_NAMES = (
    "chunk_count_distribution",
    "duration_milliseconds",
    "high_chunk_pages",
    "layout",
    "reference",
    "table",
    "token_count_distribution",
    "zero_chunk_pages",
)
_CONTENT_KINDS = frozenset({"prose", "table", "code_block", "code_symbol", "code_window"})
_FAILURE_CATEGORIES = frozenset(
    {
        "raw_page_read_failed",
        "raw_page_envelope_invalid",
        "raw_page_status_failed",
        "source_version_mismatch",
        "document_identity_mismatch",
        "normalization_failed",
        "structure_failed",
        "chunking_failed",
        "internal_failure",
    }
)


class MiniCorpusAcceptanceFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    EXTERNAL_INPUT = "external_input"
    SOURCE_INVALID = "source_invalid"
    PROCESSING_FAILED = "processing_failed"
    NONDETERMINISTIC = "nondeterministic"
    MUTATION_DETECTED = "mutation_detected"
    NEGATIVE_PROBE_FAILED = "negative_probe_failed"
    REPORT_INVALID = "report_invalid"


class MiniCorpusAcceptanceError(Exception):
    """Sanitized aggregate-only acceptance failure."""

    def __init__(self, category: MiniCorpusAcceptanceFailureCategory) -> None:
        if not isinstance(category, MiniCorpusAcceptanceFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category.value!r})"


@dataclass(frozen=True, repr=False)
class MiniCorpusAcceptanceRequest:
    run_id: CrawlRunId
    generation_id: CrawlRunId
    items: tuple[ConfluencePageWorkItem, ...]
    profile_identity: str = ACTIVE_PAGE_SET_PROFILE_IDENTITY

    def __post_init__(self) -> None:
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId:
            raise TypeError("run identity is invalid")
        try:
            rebuilt_run = CrawlRunId(self.run_id.value)
            rebuilt_generation = CrawlRunId(self.generation_id.value)
        except Exception:
            raise ValueError("run identity is invalid") from None
        if rebuilt_run != rebuilt_generation:
            raise ValueError("run and generation identity must match")
        if type(self.items) is not tuple or not 10 <= len(self.items) <= 20:
            raise ValueError("selection size is invalid")
        if any(type(item) is not ConfluencePageWorkItem for item in self.items):
            raise TypeError("selection items are invalid")
        try:
            rebuilt_items = tuple(
                ConfluencePageWorkItem(
                    page_id=item.page_id,
                    crawled_at=item.crawled_at,
                    expected_source_version=item.expected_source_version,
                )
                for item in self.items
            )
        except (TypeError, ValueError):
            raise ValueError("selection items are invalid") from None
        page_ids = tuple(item.page_id for item in rebuilt_items)
        if len(set(page_ids)) != len(page_ids):
            raise ValueError("selection contains duplicate pages")
        if type(self.profile_identity) is not str or self.profile_identity != ACTIVE_PAGE_SET_PROFILE_IDENTITY:
            raise ValueError("profile identity is invalid")
        object.__setattr__(self, "run_id", rebuilt_run)
        object.__setattr__(self, "generation_id", rebuilt_generation)
        object.__setattr__(self, "items", rebuilt_items)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(page_count={len(self.items)})"


def _require_non_negative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} is invalid")
    return value


def _require_digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _require_distribution(value: object, field: str) -> tuple[int, int, int, int]:
    if type(value) is not tuple or len(value) != 4 or any(type(item) is not int for item in value):
        raise TypeError(f"{field} is invalid")
    if any(item < 0 for item in value):
        raise ValueError(f"{field} is invalid")
    return value


@dataclass(frozen=True, repr=False)
class MiniCorpusAcceptanceSummary:
    status: str
    requested_pages: int
    succeeded_pages: int
    failed_pages: int
    chunk_count: int
    warning_count: int
    reference_intent_count: int
    content_kind_counts: tuple[tuple[str, int], ...]
    chunk_count_distribution: tuple[int, int, int, int]
    token_count_distribution: tuple[int, int, int, int]
    zero_chunk_pages: int
    table_page_count: int
    layout_page_count: int
    reference_page_count: int
    page_set_digest: str
    chunk_stability_digest: str
    first_page_set_digest: str
    second_page_set_digest: str
    first_chunk_stability_digest: str
    second_chunk_stability_digest: str
    tokenizer_asset_digest: str
    profile_identity: str
    chunker_version: str
    deterministic_repeat: bool
    source_unchanged: bool
    negative_pass: bool
    no_writes: bool
    report_leak_free: bool
    distribution_labels: tuple[tuple[str, str], ...]
    ordinal_statuses: tuple[tuple[int, str, str | None], ...]
    duration_milliseconds: int

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("status is invalid")
        counters = (
            (self.requested_pages, "requested_pages"),
            (self.succeeded_pages, "succeeded_pages"),
            (self.failed_pages, "failed_pages"),
            (self.chunk_count, "chunk_count"),
            (self.warning_count, "warning_count"),
            (self.reference_intent_count, "reference_intent_count"),
            (self.zero_chunk_pages, "zero_chunk_pages"),
            (self.table_page_count, "table_page_count"),
            (self.layout_page_count, "layout_page_count"),
            (self.reference_page_count, "reference_page_count"),
            (self.duration_milliseconds, "duration_milliseconds"),
        )
        for value, field in counters:
            _require_non_negative(value, field)
        if self.succeeded_pages + self.failed_pages != self.requested_pages:
            raise ValueError("page counters are inconsistent")
        if self.zero_chunk_pages > self.requested_pages:
            raise ValueError("zero_chunk_pages is invalid")
        if any(
            value > self.requested_pages
            for value in (self.table_page_count, self.layout_page_count, self.reference_page_count)
        ):
            raise ValueError("coverage counters are invalid")
        if any(value > self.succeeded_pages for value in (self.zero_chunk_pages, self.table_page_count, self.layout_page_count, self.reference_page_count)):
            raise ValueError("page observations exceed succeeded pages")
        if type(self.deterministic_repeat) is not bool or type(self.source_unchanged) is not bool:
            raise TypeError("acceptance booleans are invalid")
        if type(self.negative_pass) is not bool or type(self.no_writes) is not bool:
            raise TypeError("acceptance booleans are invalid")
        if type(self.report_leak_free) is not bool:
            raise TypeError("acceptance booleans are invalid")
        if self.status == "complete":
            if not 10 <= self.requested_pages <= 20 or self.failed_pages != 0 or self.succeeded_pages != self.requested_pages:
                raise ValueError("complete selection is invalid")
            if not all(
                value
                for value in (
                    self.deterministic_repeat,
                    self.source_unchanged,
                    self.negative_pass,
                    self.no_writes,
                    self.report_leak_free,
                )
            ):
                raise ValueError("complete acceptance gates are invalid")
        elif self.status == "pending_external_input":
            if any((self.requested_pages, self.succeeded_pages, self.failed_pages, self.chunk_count, self.warning_count, self.reference_intent_count, self.zero_chunk_pages, self.table_page_count, self.layout_page_count, self.reference_page_count)):
                raise ValueError("pending acceptance counters are invalid")
            if any((self.deterministic_repeat, self.source_unchanged, self.negative_pass, self.no_writes, self.report_leak_free)):
                raise ValueError("pending acceptance gates are invalid")
        elif self.failed_pages == 0 or self.requested_pages == 0:
            raise ValueError("failed acceptance counters are invalid")
        if type(self.content_kind_counts) is not tuple:
            raise TypeError("content_kind_counts is invalid")
        previous_kind: str | None = None
        for kind, count in self.content_kind_counts:
            if type(kind) is not str or kind not in _CONTENT_KINDS or type(count) is not int or count < 0:
                raise ValueError("content_kind_counts is invalid")
            if previous_kind is not None and kind <= previous_kind:
                raise ValueError("content_kind_counts ordering is invalid")
            previous_kind = kind
        if sum(count for _, count in self.content_kind_counts) != self.chunk_count:
            raise ValueError("chunk counters are inconsistent")
        for distribution, field in (
            (self.chunk_count_distribution, "chunk_count_distribution"),
            (self.token_count_distribution, "token_count_distribution"),
        ):
            values = _require_distribution(distribution, field)
            if tuple(sorted(values)) != values:
                raise ValueError(f"{field} ordering is invalid")
        chunk_distribution = self.chunk_count_distribution
        token_distribution = self.token_count_distribution
        if self.succeeded_pages == 0:
            if chunk_distribution != (0, 0, 0, 0) or token_distribution != (0, 0, 0, 0):
                raise ValueError("empty distributions are invalid")
        else:
            if self.chunk_count == 0 and token_distribution != (0, 0, 0, 0):
                raise ValueError("token distribution does not match chunk count")
            if self.chunk_count > 0 and token_distribution[3] == 0:
                raise ValueError("token distribution does not match chunk count")
            if (self.zero_chunk_pages == 0 and chunk_distribution[0] == 0) or (
                self.zero_chunk_pages > 0 and chunk_distribution[0] != 0
            ):
                raise ValueError("chunk distribution does not match zero-page count")
            if self.chunk_count == 0 and chunk_distribution[3] != 0:
                raise ValueError("chunk distribution does not match chunk count")
            if self.chunk_count > 0 and chunk_distribution[3] == 0:
                raise ValueError("chunk distribution does not match chunk count")
            if chunk_distribution[3] > self.chunk_count:
                raise ValueError("chunk distribution exceeds total chunks")
            minimum_total = self.succeeded_pages * chunk_distribution[0]
            maximum_total = self.succeeded_pages * chunk_distribution[3]
            if not minimum_total <= self.chunk_count <= maximum_total:
                raise ValueError("chunk distribution does not bound total chunks")
        if self.status == "pending_external_input" and (
            self.chunk_count_distribution != (0, 0, 0, 0)
            or self.token_count_distribution != (0, 0, 0, 0)
            or self.duration_milliseconds != 0
        ):
            raise ValueError("pending observations are invalid")
        _require_digest(self.page_set_digest, "page_set_digest")
        _require_digest(self.chunk_stability_digest, "chunk_stability_digest")
        for digest, field in (
            (self.first_page_set_digest, "first_page_set_digest"),
            (self.second_page_set_digest, "second_page_set_digest"),
            (self.first_chunk_stability_digest, "first_chunk_stability_digest"),
            (self.second_chunk_stability_digest, "second_chunk_stability_digest"),
            (self.tokenizer_asset_digest, "tokenizer_asset_digest"),
        ):
            _require_digest(digest, field)
        if self.page_set_digest != self.first_page_set_digest or self.chunk_stability_digest != self.first_chunk_stability_digest:
            raise ValueError("primary digests are inconsistent")
        if self.status == "complete" and (
            self.first_page_set_digest != self.second_page_set_digest
            or self.first_chunk_stability_digest != self.second_chunk_stability_digest
        ):
            raise ValueError("repeat digests are inconsistent")
        if self.status == "pending_external_input" and any(
            digest != _ZERO_DIGEST
            for digest in (
                self.page_set_digest,
                self.chunk_stability_digest,
                self.first_page_set_digest,
                self.second_page_set_digest,
                self.first_chunk_stability_digest,
                self.second_chunk_stability_digest,
                self.tokenizer_asset_digest,
            )
        ):
            raise ValueError("pending digests are invalid")
        if type(self.profile_identity) is not str or self.profile_identity != ACTIVE_PAGE_SET_PROFILE_IDENTITY:
            raise ValueError("profile_identity is invalid")
        if type(self.chunker_version) is not str or self.chunker_version != ACTIVE_CHUNKER_VERSION:
            raise ValueError("chunker_version is invalid")
        if type(self.distribution_labels) is not tuple:
            raise TypeError("distribution_labels is invalid")
        label_names: list[str] = []
        for name, label in self.distribution_labels:
            if type(name) is not str or name not in _LABEL_NAMES or type(label) is not str or label not in _LABELS:
                raise ValueError("distribution_labels is invalid")
            label_names.append(name)
        if tuple(label_names) != _LABEL_NAMES:
            raise ValueError("distribution_labels ordering is invalid")
        labels = dict(self.distribution_labels)
        if self.status == "pending_external_input":
            if any(label != "NOT_APPLICABLE" for label in labels.values()):
                raise ValueError("pending observation labels are invalid")
        else:
            expected_labels = {
                "chunk_count_distribution": "OBSERVED" if self.succeeded_pages else "NOT_APPLICABLE",
                "duration_milliseconds": "OBSERVED",
                "high_chunk_pages": "OBSERVED" if self.chunk_count_distribution[3] > 1 else "NOT_APPLICABLE",
                "layout": "OBSERVED" if self.layout_page_count else "NOT_APPLICABLE",
                "reference": "OBSERVED" if self.reference_page_count else "NOT_APPLICABLE",
                "table": "OBSERVED" if self.table_page_count else "NOT_APPLICABLE",
                "token_count_distribution": "OBSERVED" if self.chunk_count else "NOT_APPLICABLE",
                "zero_chunk_pages": "OBSERVED" if self.zero_chunk_pages else "NOT_APPLICABLE",
            }
            if labels != expected_labels:
                raise ValueError("distribution labels do not match observations")
        if type(self.ordinal_statuses) is not tuple:
            raise TypeError("ordinal_statuses is invalid")
        expected_ordinal = 1
        for ordinal, status, category in self.ordinal_statuses:
            if type(ordinal) is not int or ordinal != expected_ordinal:
                raise ValueError("ordinal_statuses ordering is invalid")
            if type(status) is not str or status not in {"succeeded", "failed"}:
                raise ValueError("ordinal_statuses status is invalid")
            if status == "succeeded" and category is not None:
                raise ValueError("successful ordinal has a failure category")
            if status == "failed" and (type(category) is not str or category not in _FAILURE_CATEGORIES):
                raise ValueError("ordinal_statuses category is invalid")
            expected_ordinal += 1
        if len(self.ordinal_statuses) != self.requested_pages:
            raise ValueError("ordinal_statuses count is invalid")
        ordinal_succeeded = sum(status == "succeeded" for _, status, _ in self.ordinal_statuses)
        ordinal_failed = sum(status == "failed" for _, status, _ in self.ordinal_statuses)
        if (ordinal_succeeded, ordinal_failed) != (self.succeeded_pages, self.failed_pages):
            raise ValueError("ordinal status counters are inconsistent")
        if self.status == "complete" and any(status != "succeeded" for _, status, _ in self.ordinal_statuses):
            raise ValueError("complete ordinal status is invalid")

    def to_bytes(self) -> bytes:
        payload = {
            "chunk_count": self.chunk_count,
            "chunk_count_distribution": list(self.chunk_count_distribution),
            "chunk_stability_digest": self.chunk_stability_digest,
            "first_chunk_stability_digest": self.first_chunk_stability_digest,
            "first_page_set_digest": self.first_page_set_digest,
            "chunker_version": self.chunker_version,
            "content_kind_counts": [list(item) for item in self.content_kind_counts],
            "deterministic_repeat": self.deterministic_repeat,
            "distribution_labels": [list(item) for item in self.distribution_labels],
            "duration_milliseconds": self.duration_milliseconds,
            "failed_pages": self.failed_pages,
            "layout_page_count": self.layout_page_count,
            "negative_pass": self.negative_pass,
            "no_writes": self.no_writes,
            "ordinal_statuses": [list(item) for item in self.ordinal_statuses],
            "page_set_digest": self.page_set_digest,
            "profile_identity": self.profile_identity,
            "reference_intent_count": self.reference_intent_count,
            "reference_page_count": self.reference_page_count,
            "report_leak_free": self.report_leak_free,
            "requested_pages": self.requested_pages,
            "source_unchanged": self.source_unchanged,
            "status": self.status,
            "second_chunk_stability_digest": self.second_chunk_stability_digest,
            "second_page_set_digest": self.second_page_set_digest,
            "succeeded_pages": self.succeeded_pages,
            "table_page_count": self.table_page_count,
            "token_count_distribution": list(self.token_count_distribution),
            "tokenizer_asset_digest": self.tokenizer_asset_digest,
            "warning_count": self.warning_count,
            "zero_chunk_pages": self.zero_chunk_pages,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r}, requested_pages={self.requested_pages})"


__all__ = [
    "MiniCorpusAcceptanceError",
    "MiniCorpusAcceptanceFailureCategory",
    "MiniCorpusAcceptanceRequest",
    "MiniCorpusAcceptanceSummary",
]
