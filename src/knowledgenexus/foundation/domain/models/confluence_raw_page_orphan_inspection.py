from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


class ConfluenceRawPageOrphanInspectionDecision(StrEnum):
    MISSING = "missing"
    REPLAYABLE = "replayable"
    IDENTITY_CONFLICT = "identity_conflict"
    INVALID = "invalid"
    UNSAFE_TARGET = "unsafe_target"


class ConfluenceRawPageOrphanInspectionFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    RAW_ROOT_INVALID = "raw_root_invalid"
    INSPECTION_FAILED = "inspection_failed"


class ConfluenceRawPageOrphanInspectionError(Exception):
    """Sanitized failure at the raw-page orphan inspection boundary."""

    def __init__(
        self,
        category: ConfluenceRawPageOrphanInspectionFailureCategory,
    ) -> None:
        if not isinstance(category, ConfluenceRawPageOrphanInspectionFailureCategory):
            raise TypeError("category expects ConfluenceRawPageOrphanInspectionFailureCategory")
        self.category = category
        super().__init__(category.value)


def _validated_run_id(value: object) -> CrawlRunId:
    if type(value) is not CrawlRunId:
        raise TypeError("run identity is invalid")
    try:
        rebuilt = CrawlRunId(value.value)
    except Exception:
        raise ValueError("run identity is invalid") from None
    if rebuilt != value:
        raise ValueError("run identity is invalid")
    return rebuilt


def _validated_source_version(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("source identity is invalid")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("source identity is invalid")
    return value


@dataclass(frozen=True, repr=False)
class ConfluenceRawPageOrphanInspectionRequest:
    """Exact identity binding for one offline raw-page inspection."""

    request_profile_version: str
    run_id: CrawlRunId
    generation_id: CrawlRunId
    page_id: str
    source_version: str | None

    def __post_init__(self) -> None:
        if self.request_profile_version != M7_RAW_PAGE_REQUEST_PROFILE_VERSION:
            raise ValueError("request profile version is invalid")
        run_id = _validated_run_id(self.run_id)
        generation_id = _validated_run_id(self.generation_id)
        if run_id != generation_id:
            raise ValueError("run and generation identities are invalid")
        try:
            page_id = require_confluence_page_id(self.page_id)
        except (TypeError, ValueError):
            raise ValueError("page identity is invalid") from None
        source_version = _validated_source_version(self.source_version)
        object.__setattr__(self, "request_profile_version", M7_RAW_PAGE_REQUEST_PROFILE_VERSION)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "generation_id", generation_id)
        object.__setattr__(self, "page_id", page_id)
        object.__setattr__(self, "source_version", source_version)

    @classmethod
    def capture(
        cls,
        *,
        run_id: CrawlRunId,
        generation_id: CrawlRunId,
        page_id: str,
        source_version: str | None,
        request_profile_version: str = M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
    ) -> Self:
        return cls(
            request_profile_version=request_profile_version,
            run_id=run_id,
            generation_id=generation_id,
            page_id=page_id,
            source_version=source_version,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ConfluenceRawPageOrphanInspectionResult:
    """Sanitized decision from one offline raw-page inspection."""

    decision: ConfluenceRawPageOrphanInspectionDecision
    envelope: ConfluenceRawPageEnvelope | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ConfluenceRawPageOrphanInspectionDecision):
            raise TypeError("decision is invalid")
        if self.envelope is not None and type(self.envelope) is not ConfluenceRawPageEnvelope:
            raise TypeError("envelope is invalid")
        if self.decision is ConfluenceRawPageOrphanInspectionDecision.REPLAYABLE:
            if self.envelope is None:
                raise ValueError("replayable result requires an envelope")
        elif self.envelope is not None:
            raise ValueError("non-replayable result cannot carry an envelope")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(decision={self.decision.value!r})"


__all__ = [
    "ConfluenceRawPageOrphanInspectionDecision",
    "ConfluenceRawPageOrphanInspectionError",
    "ConfluenceRawPageOrphanInspectionFailureCategory",
    "ConfluenceRawPageOrphanInspectionRequest",
    "ConfluenceRawPageOrphanInspectionResult",
]
