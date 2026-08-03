from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_artifact import (
    ConfluenceRawRestrictionArtifact,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
)


class ConfluenceRawRestrictionStoreFailureCategory(StrEnum):
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"
    RAW_IDENTITY_MISMATCH = "raw_identity_mismatch"
    RAW_REPLAY_CONFLICT = "raw_replay_conflict"
    RAW_PUBLICATION_FAILURE = "raw_publication_failure"


class ConfluenceRawRestrictionStoreError(Exception):
    """Sanitized failure from the M7 generation-scoped restriction store."""

    def __init__(self, category: ConfluenceRawRestrictionStoreFailureCategory) -> None:
        if not isinstance(category, ConfluenceRawRestrictionStoreFailureCategory):
            raise TypeError("category expects ConfluenceRawRestrictionStoreFailureCategory")
        self.category = category
        super().__init__(category.value)


class ConfluenceRawRestrictionStorePort(Protocol):
    def resolve_restriction_path(
        self,
        *,
        run_id: CrawlRunId,
        selected_page_id: str,
        target_page_id: str,
    ) -> Path: ...

    def publish_restriction(
        self,
        *,
        run_id: CrawlRunId,
        envelope: ConfluenceRestrictionEvidenceEnvelope,
    ) -> ConfluenceRawRestrictionArtifact: ...

    def read_restriction(
        self,
        *,
        run_id: CrawlRunId,
        selected_page_id: str,
        target_page_id: str,
    ) -> ConfluenceRestrictionEvidenceEnvelope: ...


__all__ = [
    "ConfluenceRawRestrictionStoreError",
    "ConfluenceRawRestrictionStoreFailureCategory",
    "ConfluenceRawRestrictionStorePort",
]
