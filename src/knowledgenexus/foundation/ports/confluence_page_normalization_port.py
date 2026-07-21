from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageSource,
    ConfluenceStorageNormalization,
)


class ConfluenceRawPageMappingError(Exception):
    """A preserved page did not match the trusted M6C input shape."""


class ConfluenceStorageNormalizationError(Exception):
    """Confluence storage XHTML could not be normalized safely."""


class ConfluenceRawPageMapperPort(Protocol):
    def map_page(
        self,
        *,
        raw_bytes: bytes,
        expected_page_id: str,
    ) -> ConfluencePageSource: ...


class ConfluenceStorageNormalizerPort(Protocol):
    def normalize(self, *, storage_xhtml: str) -> ConfluenceStorageNormalization: ...
