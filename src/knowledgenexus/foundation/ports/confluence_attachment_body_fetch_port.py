from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    RawHttpObservation,
)


class _ConfluenceAttachmentBodyFetchFailureCategory(StrEnum):
    FETCH = "fetch"
    RESPONSE_SIZE_LIMIT = "response_size_limit"


class ConfluenceAttachmentBodyFetchError(Exception):
    """An attachment body could not be fetched safely."""

    def __init__(
        self,
        category: _ConfluenceAttachmentBodyFetchFailureCategory =
        _ConfluenceAttachmentBodyFetchFailureCategory.FETCH,
    ) -> None:
        if not isinstance(category, _ConfluenceAttachmentBodyFetchFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        try:
            category = self.category.value
        except Exception:
            return f"{type(self).__name__}()"
        return f"{type(self).__name__}(category={category!r})"


class ConfluenceAttachmentBodyTooLargeError(ConfluenceAttachmentBodyFetchError):
    """An attachment body exceeded the configured byte bound."""

    def __init__(self) -> None:
        super().__init__(
            _ConfluenceAttachmentBodyFetchFailureCategory.RESPONSE_SIZE_LIMIT
        )


class ConfluenceAttachmentBodyFetchPort(Protocol):
    def fetch_attachment_body(
        self,
        *,
        attachment_id: str,
        filename: str,
        max_bytes: int,
    ) -> RawHttpObservation: ...


__all__ = [
    "ConfluenceAttachmentBodyFetchError",
    "ConfluenceAttachmentBodyFetchPort",
    "ConfluenceAttachmentBodyTooLargeError",
]
