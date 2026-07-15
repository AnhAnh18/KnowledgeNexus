from __future__ import annotations

from collections.abc import Iterable

from knowledgenexus.foundation.domain.models.confluence_inventory_item import (
    ConfluenceScopeStatus,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceExcludeSubtree,
)


class ConfluenceScopePolicy:
    """Pure deterministic include/exclude classification for inventory pages."""

    @staticmethod
    def decide(
        *,
        page: ConfluencePageMetadata,
        include_root_ids: Iterable[str],
        exclude_subtrees: Iterable[ConfluenceExcludeSubtree],
    ) -> tuple[ConfluenceScopeStatus, str]:
        include_ids = frozenset(include_root_ids)
        excluded_ids = frozenset(subtree.page_id for subtree in exclude_subtrees)

        if page.page_id in excluded_ids:
            return "excluded_subtree", f"excluded_page:{page.page_id}"

        for ancestor_page_id in reversed(page.ancestor_page_ids):
            if ancestor_page_id in excluded_ids:
                return (
                    "excluded_subtree",
                    f"excluded_ancestor:{ancestor_page_id}",
                )

        if page.page_id in include_ids:
            return "included", "included_root"
        return "included", "included_descendant"
