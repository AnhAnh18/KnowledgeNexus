from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


class ConfluenceRawRestrictionOrphanInspectionDecision(StrEnum):
    MISSING = "missing"
    REPLAYABLE = "replayable"
    IDENTITY_CONFLICT = "identity_conflict"
    INVALID = "invalid"
    UNSAFE_TARGET = "unsafe_target"


class ConfluenceRawRestrictionOrphanInspectionFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    RAW_ROOT_INVALID = "raw_root_invalid"
    INSPECTION_FAILED = "inspection_failed"


class ConfluenceRawRestrictionOrphanInspectionError(Exception):
    """Sanitized failure at the restriction orphan-inspection boundary."""

    def __init__(
        self,
        category: ConfluenceRawRestrictionOrphanInspectionFailureCategory,
    ) -> None:
        if not isinstance(
            category, ConfluenceRawRestrictionOrphanInspectionFailureCategory
        ):
            raise TypeError(
                "category expects ConfluenceRawRestrictionOrphanInspectionFailureCategory"
            )
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


def _validated_page_id(value: object) -> str:
    try:
        return require_confluence_page_id(value)
    except (TypeError, ValueError):
        raise ValueError("page identity is invalid") from None


@dataclass(frozen=True, repr=False)
class ConfluenceRawRestrictionOrphanInspectionRequest:
    """Exact path/evidence identity for one offline restriction inspection."""

    request_profile_version: str
    run_id: CrawlRunId
    selected_page_id: str
    target_page_id: str

    def __post_init__(self) -> None:
        if self.request_profile_version != M7_RESTRICTION_REQUEST_PROFILE_VERSION:
            raise ValueError("request profile version is invalid")
        run_id = _validated_run_id(self.run_id)
        selected = _validated_page_id(self.selected_page_id)
        target = _validated_page_id(self.target_page_id)
        object.__setattr__(
            self,
            "request_profile_version",
            M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        )
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "selected_page_id", selected)
        object.__setattr__(self, "target_page_id", target)

    @classmethod
    def capture(
        cls,
        *,
        run_id: CrawlRunId,
        selected_page_id: str,
        target_page_id: str,
        request_profile_version: str = M7_RESTRICTION_REQUEST_PROFILE_VERSION,
    ) -> Self:
        return cls(
            request_profile_version=request_profile_version,
            run_id=run_id,
            selected_page_id=selected_page_id,
            target_page_id=target_page_id,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ConfluenceRawRestrictionOrphanInspectionResult:
    """Sanitized decision from one offline restriction inspection."""

    decision: ConfluenceRawRestrictionOrphanInspectionDecision
    envelope: ConfluenceRestrictionEvidenceEnvelope | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.decision, ConfluenceRawRestrictionOrphanInspectionDecision
        ):
            raise TypeError("decision is invalid")
        if self.envelope is not None and type(
            self.envelope
        ) is not ConfluenceRestrictionEvidenceEnvelope:
            raise TypeError("envelope is invalid")
        if self.decision is ConfluenceRawRestrictionOrphanInspectionDecision.REPLAYABLE:
            if self.envelope is None:
                raise ValueError("replayable result requires an envelope")
        elif self.envelope is not None:
            raise ValueError("non-replayable result cannot carry an envelope")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(decision={self.decision.value!r})"


__all__ = [
    "ConfluenceRawRestrictionOrphanInspectionDecision",
    "ConfluenceRawRestrictionOrphanInspectionError",
    "ConfluenceRawRestrictionOrphanInspectionFailureCategory",
    "ConfluenceRawRestrictionOrphanInspectionRequest",
    "ConfluenceRawRestrictionOrphanInspectionResult",
]
