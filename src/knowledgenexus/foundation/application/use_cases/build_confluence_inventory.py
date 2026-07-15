from __future__ import annotations

from knowledgenexus.foundation.domain.models.confluence_inventory_item import (
    ConfluenceInventoryItem,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.domain.rules.confluence_scope_policy import (
    ConfluenceScopePolicy,
)
from knowledgenexus.foundation.ports.confluence_inventory_port import (
    ConfluenceInventoryPort,
)


class BuildConfluenceInventory:
    def __init__(self, *, inventory_port: ConfluenceInventoryPort) -> None:
        self._inventory_port = inventory_port

    def execute(
        self,
        *,
        config: ConfluenceSourceConfig,
    ) -> tuple[ConfluenceInventoryItem, ...]:
        metadata_by_page_id: dict[str, ConfluencePageMetadata] = {}

        for root in sorted(config.include_roots, key=lambda item: item.page_id):
            root_found = False
            pages = self._inventory_port.iter_page_metadata(
                space_key=config.space_key,
                root_page_id=root.page_id,
                page_size=config.page_size,
            )
            for page in pages:
                self._validate_page(
                    page=page,
                    space_key=config.space_key,
                    root_page_id=root.page_id,
                )
                if page.page_id == root.page_id:
                    root_found = True
                existing = metadata_by_page_id.get(page.page_id)
                if existing is not None and existing != page:
                    raise ValueError(
                        "Confluence inventory returned conflicting metadata for "
                        f"page_id {page.page_id!r}"
                    )
                metadata_by_page_id[page.page_id] = page

            if not root_found:
                raise ValueError(
                    "Confluence inventory result is missing requested root page "
                    f"{root.page_id!r}"
                )

        include_root_ids = tuple(root.page_id for root in config.include_roots)
        items = []
        for page in metadata_by_page_id.values():
            scope_status, scope_reason = ConfluenceScopePolicy.decide(
                page=page,
                include_root_ids=include_root_ids,
                exclude_subtrees=config.exclude_subtrees,
            )
            items.append(
                ConfluenceInventoryItem.from_metadata(
                    source_id=config.source_id,
                    metadata=page,
                    scope_status=scope_status,
                    scope_reason=scope_reason,
                )
            )

        return tuple(
            sorted(
                items,
                key=lambda item: (
                    item.space_key,
                    item.ancestor_page_ids,
                    item.page_id,
                ),
            )
        )

    @staticmethod
    def _validate_page(
        *,
        page: ConfluencePageMetadata,
        space_key: str,
        root_page_id: str,
    ) -> None:
        if not isinstance(page, ConfluencePageMetadata):
            raise TypeError(
                "ConfluenceInventoryPort must return ConfluencePageMetadata"
            )
        if page.space_key != space_key:
            raise ValueError(
                "Confluence inventory returned page from wrong space: "
                f"{page.page_id!r}"
            )
        if page.page_id != root_page_id and root_page_id not in page.ancestor_page_ids:
            raise ValueError(
                "Confluence inventory returned page outside requested root: "
                f"{page.page_id!r}"
            )
