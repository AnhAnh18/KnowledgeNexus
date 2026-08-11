"""Production composition for a bounded, one-root Confluence inventory.

The M7 inventory use case owns checkpointing, run selection and pagination.  This
module only adds the subtree contract: one include root and a hard page bound.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from knowledgenexus.foundation.application.use_cases.execute_durable_confluence_inventory import (
    DurableInventoryRunResult,
    DurableInventoryTransportFactory,
    ExecuteDurableConfluenceInventory,
)
from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import ControlledStopPolicy
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceSourceConfig
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import CheckpointStateError
from knowledgenexus.foundation.ports.confluence_inventory_window_port import ConfluenceInventoryWindowPort
from knowledgenexus.foundation.domain.models.confluence_inventory_window import ConfluenceInventoryWindow

MAX_SUBTREE_PAGES = 5_000
SubtreeInventoryRequest = StartNewRunRequest | ResumeExplicitRunRequest | ResumeUniqueIncompleteRunRequest


@dataclass(frozen=True)
class BoundedInventoryResult:
    """Result plus the number of inventory pages durably observed."""

    result: DurableInventoryRunResult
    selected_pages: int

    def __post_init__(self) -> None:
        if type(self.result) is not DurableInventoryRunResult or type(self.selected_pages) is not int or self.selected_pages < 0 or self.selected_pages > MAX_SUBTREE_PAGES:
            raise ValueError("invalid bounded inventory result")


class _BoundedWindowPort:
    def __init__(self, inner: ConfluenceInventoryWindowPort, *, max_pages: int) -> None:
        if not callable(getattr(inner, "fetch_root_metadata", None)) or not callable(getattr(inner, "fetch_descendants_window", None)):
            raise TypeError("inventory window port is invalid")
        self._inner = inner
        self._max_pages = max_pages
        self._selected = 0

    @property
    def selected_pages(self) -> int:
        return self._selected

    def fetch_root_metadata(self, *, space_key: str, root_page_id: str) -> ConfluencePageMetadata:
        if type(space_key) is not str or not space_key or type(root_page_id) is not str or not root_page_id:
            raise CheckpointStateError()
        if self._selected >= self._max_pages:
            raise CheckpointStateError()
        value = self._inner.fetch_root_metadata(space_key=space_key, root_page_id=root_page_id)
        if type(value) is not ConfluencePageMetadata:
            raise CheckpointStateError()
        self._selected += 1
        return value

    def fetch_descendants_window(self, *, space_key: str, root_page_id: str, start: int, page_size: int) -> ConfluenceInventoryWindow:
        if type(space_key) is not str or not space_key or type(root_page_id) is not str or not root_page_id or type(start) is not int or start < 0 or type(page_size) is not int or page_size <= 0:
            raise CheckpointStateError()
        if self._selected + page_size > self._max_pages:
            raise CheckpointStateError()
        value = self._inner.fetch_descendants_window(space_key=space_key, root_page_id=root_page_id, start=start, page_size=page_size)
        if type(value) is not ConfluenceInventoryWindow:
            raise CheckpointStateError()
        if self._selected + len(value.items) > self._max_pages:
            raise CheckpointStateError()
        self._selected += len(value.items)
        return value


class ExecuteBoundedConfluenceInventory:
    """Compose the approved durable inventory executor with subtree bounds."""

    def __init__(self, *, checkpoint_run_port: object, inventory_window_port_factory: Callable[[object], ConfluenceInventoryWindowPort], inventory_transport_factory: DurableInventoryTransportFactory, max_pages: int = MAX_SUBTREE_PAGES) -> None:
        if type(max_pages) is not int or max_pages <= 0 or max_pages > MAX_SUBTREE_PAGES:
            raise ValueError("max_pages must be between 1 and 5000")
        if not callable(inventory_window_port_factory):
            raise TypeError("inventory_window_port_factory must be callable")
        self._checkpoint_run_port = checkpoint_run_port
        self._factory = inventory_window_port_factory
        self._transport_factory = inventory_transport_factory
        self._max_pages = max_pages

    def execute(self, *, request: SubtreeInventoryRequest, controlled_stop_policy: ControlledStopPolicy | None = None) -> BoundedInventoryResult:
        if type(request) not in (StartNewRunRequest, ResumeExplicitRunRequest, ResumeUniqueIncompleteRunRequest):
            raise TypeError("invalid subtree inventory request")
        if type(request.source_config) is not ConfluenceSourceConfig or len(request.source_config.include_roots) != 1:
            raise ValueError("subtree inventory requires exactly one include root")
        holder: dict[str, _BoundedWindowPort] = {}

        def factory(transport: object) -> _BoundedWindowPort:
            wrapped = _BoundedWindowPort(self._factory(transport), max_pages=self._max_pages)
            holder["port"] = wrapped
            return wrapped

        result = ExecuteDurableConfluenceInventory(
            checkpoint_run_port=self._checkpoint_run_port,
            inventory_window_port_factory=factory,
            inventory_transport_factory=self._transport_factory,
        ).execute(request=request, controlled_stop_policy=controlled_stop_policy)
        return BoundedInventoryResult(result, holder.get("port").selected_pages if holder.get("port") else 0)


__all__ = ["BoundedInventoryResult", "ExecuteBoundedConfluenceInventory", "MAX_SUBTREE_PAGES"]
