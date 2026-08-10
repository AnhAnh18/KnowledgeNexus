from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentRawArtifact,
)


class ConfluenceRawAttachmentStoreFailureCategory(StrEnum):
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"
    RAW_REPLAY_CONFLICT = "raw_replay_conflict"
    BUDGET_EXCEEDED = "budget_exceeded"
    RAW_PUBLICATION_FAILURE = "raw_publication_failure"


class ConfluenceRawAttachmentStoreError(Exception):
    """Sanitized failure from the immutable attachment raw store."""

    def __init__(self, category: ConfluenceRawAttachmentStoreFailureCategory) -> None:
        if not isinstance(category, ConfluenceRawAttachmentStoreFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        try:
            category = self.category.value
        except Exception:
            return f"{type(self).__name__}()"
        return f"{type(self).__name__}(category={category!r})"


class ConfluenceRawAttachmentStorePort(Protocol):
    def resolve_attachment_path(
        self, *, attachment_id: str, content_hash: str
    ) -> Path: ...

    def publish_attachment(
        self, *, envelope: MediaAttachmentBodyEnvelope
    ) -> MediaAttachmentRawArtifact: ...

    def read_attachment(
        self, *, attachment_id: str, content_hash: str
    ) -> MediaAttachmentBodyEnvelope: ...


__all__ = [
    "ConfluenceRawAttachmentStoreError",
    "ConfluenceRawAttachmentStoreFailureCategory",
    "ConfluenceRawAttachmentStorePort",
]
