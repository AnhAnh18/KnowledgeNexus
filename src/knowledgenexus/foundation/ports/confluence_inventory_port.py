from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)


class ConfluenceInventoryPort(Protocol):
    """Normalized inventory metadata required by the M5 application boundary."""

    def iter_page_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterable[ConfluencePageMetadata]: ...
