from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.raw_page_artifact import RawPageArtifact


class RawPageStoreError(Exception):
    """A raw page could not be published. Sanitized: carries no content."""


class RawPageStorePort(Protocol):
    """Persists one raw page response at a deterministic, replaceable path."""

    def write(self, *, page_id: str, raw_bytes: bytes) -> RawPageArtifact: ...
