from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)


ConfluenceScopeStatus = Literal["included", "excluded_subtree"]
VALID_SCOPE_STATUSES = frozenset({"included", "excluded_subtree"})


@dataclass(frozen=True)
class ConfluenceInventoryItem:
    source_id: str
    page_id: str
    title: str
    space_key: str
    parent_page_id: str | None
    ancestor_page_ids: tuple[str, ...]
    ancestor_titles: tuple[str, ...]
    updated_at: str | None
    source_version: str | None
    labels: tuple[str, ...]
    attachment_count: int | None
    scope_status: ConfluenceScopeStatus
    scope_reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str):
            raise TypeError("ConfluenceInventoryItem.source_id expects str")
        if self.source_id == "":
            raise ValueError("ConfluenceInventoryItem.source_id must not be empty")
        if self.scope_status not in VALID_SCOPE_STATUSES:
            raise ValueError(
                "ConfluenceInventoryItem.scope_status must be included or "
                "excluded_subtree"
            )
        if not isinstance(self.scope_reason, str):
            raise TypeError("ConfluenceInventoryItem.scope_reason expects str")
        if self.scope_reason == "":
            raise ValueError("ConfluenceInventoryItem.scope_reason must not be empty")

        metadata = ConfluencePageMetadata(
            page_id=self.page_id,
            title=self.title,
            space_key=self.space_key,
            parent_page_id=self.parent_page_id,
            ancestor_page_ids=self.ancestor_page_ids,
            ancestor_titles=self.ancestor_titles,
            updated_at=self.updated_at,
            source_version=self.source_version,
            labels=self.labels,
            attachment_count=self.attachment_count,
        )
        object.__setattr__(self, "ancestor_page_ids", metadata.ancestor_page_ids)
        object.__setattr__(self, "ancestor_titles", metadata.ancestor_titles)
        object.__setattr__(self, "labels", metadata.labels)

    @classmethod
    def from_metadata(
        cls,
        *,
        source_id: str,
        metadata: ConfluencePageMetadata,
        scope_status: ConfluenceScopeStatus,
        scope_reason: str,
    ) -> ConfluenceInventoryItem:
        return cls(
            source_id=source_id,
            page_id=metadata.page_id,
            title=metadata.title,
            space_key=metadata.space_key,
            parent_page_id=metadata.parent_page_id,
            ancestor_page_ids=metadata.ancestor_page_ids,
            ancestor_titles=metadata.ancestor_titles,
            updated_at=metadata.updated_at,
            source_version=metadata.source_version,
            labels=metadata.labels,
            attachment_count=metadata.attachment_count,
            scope_status=scope_status,
            scope_reason=scope_reason,
        )
