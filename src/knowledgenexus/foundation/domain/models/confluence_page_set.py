from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


ACTIVE_PAGE_SET_PROFILE_IDENTITY = "bge-m3:medium:chunker-1.2.0"
_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.[0-9]+)?(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})$"
)
_CONTENT_KIND = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ConfluencePageSetFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    RAW_PAGE_READ_FAILED = "raw_page_read_failed"
    RAW_PAGE_ENVELOPE_INVALID = "raw_page_envelope_invalid"
    RAW_PAGE_STATUS_FAILED = "raw_page_status_failed"
    SOURCE_VERSION_MISMATCH = "source_version_mismatch"
    DOCUMENT_IDENTITY_MISMATCH = "document_identity_mismatch"
    NORMALIZATION_FAILED = "normalization_failed"
    STRUCTURE_FAILED = "structure_failed"
    CHUNKING_FAILED = "chunking_failed"
    INTERNAL_FAILURE = "internal_failure"


def _require_non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{field_name} expects a non-negative integer")
    return value


def _validate_timestamp(value: object) -> str:
    if type(value) is not str:
        raise TypeError("crawled_at expects str")
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ValueError("crawled_at is invalid")
    zone = match.group("zone")
    if zone != "Z":
        hours, minutes = (int(part) for part in zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError("crawled_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("crawled_at is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("crawled_at is invalid")
    return value


def _validate_source_version(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError("expected_source_version is invalid")
    if any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise ValueError("expected_source_version is invalid")
    return value


def _json_copy(value: object) -> Any:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("JSON values must be finite")
        return value
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, entry in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            copied[key] = _json_copy(entry)
        return copied
    if type(value) is list:
        return [_json_copy(entry) for entry in value]
    if type(value) is tuple:
        return [_json_copy(entry) for entry in value]
    raise TypeError("value is not JSON-compatible")


def _copy_record(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{field_name} expects dict")
    return _json_copy(value)


def _validate_counts(value: object, field_name: str) -> tuple[tuple[str, int], ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} expects tuple")
    entries: list[tuple[str, int]] = []
    previous: str | None = None
    for entry in value:
        if type(entry) is not tuple or len(entry) != 2:
            raise TypeError(f"{field_name} entries are invalid")
        name, count = entry
        if type(name) is not str or _CONTENT_KIND.fullmatch(name) is None:
            raise ValueError(f"{field_name} names are invalid")
        _require_non_negative_int(count, f"{field_name} count")
        if previous is not None and name <= previous:
            raise ValueError(f"{field_name} must be sorted and unique")
        entries.append((name, count))
        previous = name
    return tuple(entries)


@dataclass(frozen=True, repr=False)
class ConfluencePageWorkItem:
    page_id: str
    crawled_at: str
    expected_source_version: str | None = None

    def __post_init__(self) -> None:
        if type(self.page_id) is not str:
            raise TypeError("page_id is invalid")
        try:
            page_id = require_confluence_page_id(self.page_id)
        except (TypeError, ValueError):
            raise ValueError("page_id is invalid") from None
        _validate_timestamp(self.crawled_at)
        expected = _validate_source_version(self.expected_source_version)
        object.__setattr__(self, "page_id", page_id)
        object.__setattr__(self, "expected_source_version", expected)


@dataclass(frozen=True, repr=False)
class ConfluencePageSetRequest:
    run_id: CrawlRunId
    generation_id: CrawlRunId
    items: tuple[ConfluencePageWorkItem, ...]
    profile_identity: str

    def __post_init__(self) -> None:
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId:
            raise TypeError("run and generation ids are invalid")
        if self.run_id != self.generation_id:
            raise ValueError("run and generation ids must match")
        if type(self.items) is not tuple:
            raise TypeError("items must be a tuple")
        if not self.items:
            raise ValueError("items must be a non-empty tuple")
        if any(type(item) is not ConfluencePageWorkItem for item in self.items):
            raise TypeError("items contain an invalid work item")
        page_ids = tuple(item.page_id for item in self.items)
        if len(set(page_ids)) != len(page_ids):
            raise ValueError("items contain duplicate page IDs")
        if (
            type(self.profile_identity) is not str
            or self.profile_identity != ACTIVE_PAGE_SET_PROFILE_IDENTITY
        ):
            raise ValueError("profile identity is invalid")


@dataclass(frozen=True, repr=False)
class ConfluencePageSetPageMetrics:
    page_ordinal: int
    chunk_count: int
    warning_count: int
    reference_intent_count: int
    content_kind_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if type(self.page_ordinal) is not int or self.page_ordinal <= 0:
            raise ValueError("page_ordinal is invalid")
        for field_name in ("chunk_count", "warning_count", "reference_intent_count"):
            _require_non_negative_int(getattr(self, field_name), field_name)
        counts = _validate_counts(self.content_kind_counts, "content_kind_counts")
        if sum(count for _, count in counts) != self.chunk_count:
            raise ValueError("content-kind counts do not match chunk_count")
        object.__setattr__(self, "content_kind_counts", counts)


@dataclass(frozen=True, repr=False)
class ConfluencePageSetMetrics:
    requested_pages: int
    succeeded_pages: int
    failed_pages: int
    document_count: int
    chunk_count: int
    warning_count: int
    reference_intent_count: int
    content_kind_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        fields = (
            "requested_pages",
            "succeeded_pages",
            "failed_pages",
            "document_count",
            "chunk_count",
            "warning_count",
            "reference_intent_count",
        )
        for field_name in fields:
            _require_non_negative_int(getattr(self, field_name), field_name)
        if self.requested_pages != self.succeeded_pages + self.failed_pages:
            raise ValueError("page counts are inconsistent")
        if self.document_count != self.succeeded_pages:
            raise ValueError("document count is inconsistent")
        counts = _validate_counts(self.content_kind_counts, "content_kind_counts")
        if sum(count for _, count in counts) != self.chunk_count:
            raise ValueError("content-kind counts do not match chunk_count")
        object.__setattr__(self, "content_kind_counts", counts)


@dataclass(frozen=True, repr=False)
class ConfluencePageSetResult:
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    page_metrics: tuple[ConfluencePageSetPageMetrics, ...]
    metrics: ConfluencePageSetMetrics
    reference_intents_by_page: tuple[tuple[str, tuple[NormalizationReferenceIntent, ...]], ...] = ()

    def __post_init__(self) -> None:
        if type(self.documents) is not tuple or type(self.chunks) is not tuple:
            raise TypeError("records must be tuples")
        documents = tuple(_copy_record(record, "document") for record in self.documents)
        chunks = tuple(_copy_record(record, "chunk") for record in self.chunks)
        if type(self.page_metrics) is not tuple or any(
            type(item) is not ConfluencePageSetPageMetrics for item in self.page_metrics
        ):
            raise TypeError("page_metrics are invalid")
        ordinals = tuple(item.page_ordinal for item in self.page_metrics)
        if ordinals != tuple(range(1, len(ordinals) + 1)):
            raise ValueError("page_metrics ordinals are not contiguous")
        if type(self.metrics) is not ConfluencePageSetMetrics:
            raise TypeError("metrics are invalid")
        if len(documents) != self.metrics.document_count or len(chunks) != self.metrics.chunk_count:
            raise ValueError("result counts do not match metrics")
        if len(self.page_metrics) != self.metrics.succeeded_pages:
            raise ValueError("page metrics do not match succeeded pages")
        if sum(item.chunk_count for item in self.page_metrics) != self.metrics.chunk_count:
            raise ValueError("page chunk counts do not match metrics")
        if sum(item.warning_count for item in self.page_metrics) != self.metrics.warning_count:
            raise ValueError("page warning counts do not match metrics")
        if sum(item.reference_intent_count for item in self.page_metrics) != self.metrics.reference_intent_count:
            raise ValueError("page intent counts do not match metrics")
        page_kind_counts: dict[str, int] = {}
        for item in self.page_metrics:
            for kind, count in item.content_kind_counts:
                page_kind_counts[kind] = page_kind_counts.get(kind, 0) + count
        if tuple(sorted(page_kind_counts.items())) != self.metrics.content_kind_counts:
            raise ValueError("page content-kind counts do not match metrics")
        reference_intents_by_page = self._validate_reference_intents(
            self.reference_intents_by_page,
            documents,
            expected_total=self.metrics.reference_intent_count,
        )
        object.__setattr__(self, "documents", documents)
        object.__setattr__(self, "chunks", chunks)
        object.__setattr__(self, "reference_intents_by_page", reference_intents_by_page)

    @staticmethod
    def _validate_reference_intents(
        value: object,
        documents: tuple[dict[str, object], ...],
        *,
        expected_total: int,
    ) -> tuple[tuple[str, tuple[NormalizationReferenceIntent, ...]], ...]:
        if type(value) is not tuple:
            raise TypeError("reference_intents_by_page must be a tuple")
        if not value:
            if expected_total != 0:
                raise ValueError("reference intents are missing")
            return ()
        if len(value) != len(documents):
            raise ValueError("reference intent page count does not match documents")
        output: list[tuple[str, tuple[NormalizationReferenceIntent, ...]]] = []
        document_ids = tuple(record.get("document_id") for record in documents)
        for index, entry in enumerate(value):
            if type(entry) is not tuple or len(entry) != 2:
                raise TypeError("reference intent page entry is invalid")
            page_document_id, intents = entry
            if type(page_document_id) is not str or page_document_id != document_ids[index]:
                raise ValueError("reference intent page identity is invalid")
            if type(intents) is not tuple or any(type(intent) is not NormalizationReferenceIntent for intent in intents):
                raise TypeError("reference intents are invalid")
            ordinals = tuple(intent.ordinal for intent in intents)
            if ordinals != tuple(range(1, len(ordinals) + 1)):
                raise ValueError("reference intent ordinals are invalid")
            output.append((page_document_id, tuple(intents)))
        if sum(len(intents) for _, intents in output) != expected_total:
            raise ValueError("reference intent count does not match metrics")
        return tuple(output)

    def to_canonical_json(self) -> bytes:
        payload = {
            "documents": self.documents,
            "chunks": self.chunks,
            "reference_intents_by_page": [
                {
                    "document_id": document_id,
                    "reference_intents": [
                        {
                            "ordinal": intent.ordinal,
                            "kind": intent.kind,
                            "status": intent.status,
                            "target_identity": intent.target_identity,
                            "placeholder_identity": intent.placeholder_identity,
                        }
                        for intent in intents
                    ],
                }
                for document_id, intents in self.reference_intents_by_page
            ],
            "page_metrics": [
                {
                    "page_ordinal": item.page_ordinal,
                    "chunk_count": item.chunk_count,
                    "warning_count": item.warning_count,
                    "reference_intent_count": item.reference_intent_count,
                    "content_kind_counts": item.content_kind_counts,
                }
                for item in self.page_metrics
            ],
            "metrics": {
                "requested_pages": self.metrics.requested_pages,
                "succeeded_pages": self.metrics.succeeded_pages,
                "failed_pages": self.metrics.failed_pages,
                "document_count": self.metrics.document_count,
                "chunk_count": self.metrics.chunk_count,
                "warning_count": self.metrics.warning_count,
                "reference_intent_count": self.metrics.reference_intent_count,
                "content_kind_counts": self.metrics.content_kind_counts,
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


class ConfluencePageSetError(Exception):
    """Sanitized all-or-nothing page-set failure."""

    def __init__(
        self,
        category: ConfluencePageSetFailureCategory,
        *,
        page_ordinal: int,
        requested_pages: int,
        succeeded_pages: int,
    ) -> None:
        if not isinstance(category, ConfluencePageSetFailureCategory):
            raise TypeError("category is invalid")
        if type(page_ordinal) is not int or page_ordinal < 0:
            raise ValueError("page_ordinal is invalid")
        _require_non_negative_int(requested_pages, "requested_pages")
        _require_non_negative_int(succeeded_pages, "succeeded_pages")
        if succeeded_pages > requested_pages:
            raise ValueError("succeeded_pages is invalid")
        if page_ordinal > requested_pages:
            raise ValueError("page_ordinal is invalid")
        if page_ordinal == 0 and succeeded_pages != 0:
            raise ValueError("preflight error counts are invalid")
        if (category == ConfluencePageSetFailureCategory.INVALID_REQUEST) != (
            page_ordinal == 0
        ):
            raise ValueError("error category and ordinal are inconsistent")
        self.category = category
        self.page_ordinal = page_ordinal
        self.requested_pages = requested_pages
        self.succeeded_pages = succeeded_pages
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category.value!r})"


def validate_raw_page_envelope(
    envelope: object,
    *,
    request: ConfluencePageSetRequest,
    item: ConfluencePageWorkItem,
) -> ConfluenceRawPageEnvelope:
    if type(envelope) is not ConfluenceRawPageEnvelope:
        raise TypeError("raw page envelope is invalid")
    if (
        type(envelope.request_profile_version) is not str
        or type(envelope.page_id) is not str
    ):
        raise TypeError("raw page identity is invalid")
    if (
        envelope.request_profile_version != M7_RAW_PAGE_REQUEST_PROFILE_VERSION
        or envelope.run_id != request.run_id
        or envelope.generation_id != request.generation_id
        or envelope.page_id != item.page_id
    ):
        raise ValueError("raw page identity or request profile is invalid")
    if envelope.http_status != 200:
        raise ValueError("raw page status is not successful")
    if type(envelope.body_bytes) is not bytes:
        raise TypeError("raw page body is invalid")
    if envelope.source_version is not None and type(envelope.source_version) is not str:
        raise TypeError("raw page source version is invalid")
    if item.expected_source_version is not None and envelope.source_version != item.expected_source_version:
        raise ValueError("raw page source version is invalid")
    return envelope


__all__ = [
    "ACTIVE_PAGE_SET_PROFILE_IDENTITY",
    "ConfluencePageSetError",
    "ConfluencePageSetFailureCategory",
    "ConfluencePageSetMetrics",
    "ConfluencePageSetPageMetrics",
    "ConfluencePageSetRequest",
    "ConfluencePageSetResult",
    "ConfluencePageWorkItem",
    "validate_raw_page_envelope",
]
