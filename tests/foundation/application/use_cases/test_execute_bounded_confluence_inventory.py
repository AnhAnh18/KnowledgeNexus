import pytest

from knowledgenexus.foundation.application.use_cases.execute_bounded_confluence_inventory import ExecuteBoundedConfluenceInventory, MAX_SUBTREE_PAGES, _BoundedWindowPort
from knowledgenexus.foundation.domain.models.confluence_inventory_window import ConfluenceInventoryWindow
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import CheckpointStateError


def _meta(page_id):
    return ConfluencePageMetadata(page_id=page_id, title="t", space_key="S", parent_page_id=None, ancestor_page_ids=(), ancestor_titles=(), labels=(), updated_at=None, source_version="1", attachment_count=0)


class _Port:
    def fetch_root_metadata(self, **kwargs):
        return _meta("r")

    def fetch_descendants_window(self, **kwargs):
        return ConfluenceInventoryWindow(items=(_meta("p1"), _meta("p2")), start=kwargs["start"], limit=2, size=2, total_size=2)


def test_bounded_window_port_counts_and_fails_before_over_bound():
    port = _BoundedWindowPort(_Port(), max_pages=2)
    assert port.fetch_root_metadata(space_key="S", root_page_id="r").page_id == "r"
    with pytest.raises(CheckpointStateError):
        port.fetch_descendants_window(space_key="S", root_page_id="r", start=0, page_size=2)


def test_max_pages_is_hard_bounded():
    with pytest.raises(ValueError):
        ExecuteBoundedConfluenceInventory(checkpoint_run_port=object(), inventory_window_port_factory=lambda _: _Port(), inventory_transport_factory=lambda _: object(), max_pages=MAX_SUBTREE_PAGES + 1)
