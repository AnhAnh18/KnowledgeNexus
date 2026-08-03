from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)


class ConfluenceInventoryWindowPort(Protocol):
    """One-root/one-window normalized inventory acquisition seam."""

    def fetch_root_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
    ) -> ConfluencePageMetadata: ...

    def fetch_descendants_window(
        self,
        *,
        space_key: str,
        root_page_id: str,
        start: int,
        page_size: int,
    ) -> ConfluenceInventoryWindow: ...
