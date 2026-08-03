from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)


def _item(page_id: str) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id=page_id,
        title=f"Title {page_id}",
        space_key="SPACE",
    )


def test_window_derives_cursor_and_terminal_state() -> None:
    window = ConfluenceInventoryWindow(
        items=[_item("1001"), _item("1002")],
        start=2,
        limit=2,
        size=2,
        total_size=5,
    )

    assert window.items == (_item("1001"), _item("1002"))
    assert window.next_start == 4
    assert window.is_terminal is False

    terminal = ConfluenceInventoryWindow(
        items=[_item("1003")],
        start=4,
        limit=2,
        size=1,
        total_size=5,
    )
    assert terminal.next_start is None
    assert terminal.is_terminal is True


def test_window_snapshots_item_collection_and_is_frozen() -> None:
    items = [_item("1001")]
    window = ConfluenceInventoryWindow(
        items=items,
        start=0,
        limit=2,
        size=1,
        total_size=1,
    )
    items.append(_item("1002"))

    assert window.items == (_item("1001"),)
    with pytest.raises(AttributeError):
        window.start = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", True),
        ("start", 1.0),
        ("start", -1),
        ("limit", False),
        ("limit", 1.0),
        ("limit", 0),
        ("size", False),
        ("size", -1),
        ("total_size", -1),
    ],
)
def test_window_rejects_invalid_numeric_state(field: str, value: object) -> None:
    values: dict[str, object] = {
        "items": [_item("1001")],
        "start": 0,
        "limit": 1,
        "size": 1,
        "total_size": 1,
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        ConfluenceInventoryWindow(**values)  # type: ignore[arg-type]


def test_window_rejects_inconsistent_items_and_totals() -> None:
    with pytest.raises(ValueError):
        ConfluenceInventoryWindow(
            items=[], start=0, limit=2, size=1, total_size=1
        )
    with pytest.raises(ValueError):
        ConfluenceInventoryWindow(
            items=[_item("1001"), _item("1002")],
            start=0,
            limit=1,
            size=2,
            total_size=2,
        )
    with pytest.raises(ValueError):
        ConfluenceInventoryWindow(
            items=[_item("1001")], start=2, limit=2, size=1, total_size=2
        )
    with pytest.raises(ValueError, match="must advance"):
        ConfluenceInventoryWindow(
            items=[], start=0, limit=2, size=0, total_size=1
        )


def test_window_rejects_non_metadata_items() -> None:
    with pytest.raises(TypeError):
        ConfluenceInventoryWindow(
            items=["not metadata"],  # type: ignore[list-item]
            start=0,
            limit=1,
            size=1,
            total_size=1,
        )
