from __future__ import annotations

from pathlib import Path
from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageArtifact,
    ConfluenceRawPageEnvelope,
    ConfluenceRawPageStoreFailureCategory,
)


class ConfluenceRawPageStoreError(Exception):
    """Sanitized failure from the M7 generation-scoped raw-page store."""

    def __init__(self, category: ConfluenceRawPageStoreFailureCategory) -> None:
        if not isinstance(category, ConfluenceRawPageStoreFailureCategory):
            raise TypeError("category expects ConfluenceRawPageStoreFailureCategory")
        self.category = category
        super().__init__(category.value)


class ConfluenceRawPageStorePort(Protocol):
    def resolve_page_path(self, *, run_id: CrawlRunId, page_id: str) -> Path: ...

    def publish_page(self, *, envelope: ConfluenceRawPageEnvelope) -> ConfluenceRawPageArtifact: ...

    def read_page(self, *, run_id: CrawlRunId, page_id: str) -> ConfluenceRawPageEnvelope: ...


__all__ = [
    "ConfluenceRawPageStoreError",
    "ConfluenceRawPageStorePort",
]
