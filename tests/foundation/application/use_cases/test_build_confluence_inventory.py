from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from knowledgenexus.foundation.application.use_cases import BuildConfluenceInventory
from knowledgenexus.foundation.domain.models import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluencePageMetadata,
    ConfluenceSourceConfig,
)


class FakeInventoryPort:
    def __init__(self, pages_by_root: dict[str, list[ConfluencePageMetadata]]) -> None:
        self.pages_by_root = pages_by_root
        self.calls: list[tuple[str, str, int]] = []
        self.iterations = 0

    def iter_page_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterable[ConfluencePageMetadata]:
        self.calls.append((space_key, root_page_id, page_size))

        def one_pass() -> Iterator[ConfluencePageMetadata]:
            self.iterations += 1
            yield from self.pages_by_root[root_page_id]

        return one_pass()


def test_builds_root_and_descendants_and_passes_exact_port_arguments() -> None:
    root = _page("root", attachment_count=None, labels=("z", "a", "z"))
    child = _page(
        "child",
        ancestors=("root",),
        parent="root",
        attachment_count=0,
    )
    port = FakeInventoryPort({"root": [child, root]})

    items = BuildConfluenceInventory(inventory_port=port).execute(
        config=_config(page_size=17)
    )

    assert port.calls == [("SPACE", "root", 17)]
    assert port.iterations == 1
    assert {item.page_id for item in items} == {"root", "child"}
    root_item = next(item for item in items if item.page_id == "root")
    child_item = next(item for item in items if item.page_id == "child")
    assert root_item.scope_reason == "included_root"
    assert root_item.labels == ("a", "z")
    assert root_item.attachment_count is None
    assert child_item.attachment_count == 0


def test_missing_requested_root_fails() -> None:
    port = FakeInventoryPort({"root": [_page("child", ancestors=("root",))]})

    with pytest.raises(ValueError, match="missing requested root"):
        BuildConfluenceInventory(inventory_port=port).execute(config=_config())


def test_wrong_space_page_fails() -> None:
    port = FakeInventoryPort(
        {"root": [_page("root"), _page("child", ancestors=("root",), space="OTHER")]}
    )

    with pytest.raises(ValueError, match="wrong space"):
        BuildConfluenceInventory(inventory_port=port).execute(config=_config())


def test_unrelated_page_fails() -> None:
    port = FakeInventoryPort({"root": [_page("root"), _page("unrelated")]})

    with pytest.raises(ValueError, match="outside requested root"):
        BuildConfluenceInventory(inventory_port=port).execute(config=_config())


def test_overlapping_roots_deduplicate_identical_metadata() -> None:
    root = _page("root")
    nested = _page("nested", ancestors=("root",), parent="root")
    leaf = _page("leaf", ancestors=("root", "nested"), parent="nested")
    port = FakeInventoryPort(
        {
            "root": [leaf, nested, root],
            "nested": [nested, leaf],
        }
    )

    items = BuildConfluenceInventory(inventory_port=port).execute(
        config=_config(root_ids=("nested", "root"))
    )

    assert [item.page_id for item in items] == ["root", "nested", "leaf"]
    assert port.calls == [("SPACE", "nested", 25), ("SPACE", "root", 25)]


def test_conflicting_duplicate_metadata_fails() -> None:
    root = _page("root")
    nested = _page("nested", ancestors=("root",))
    conflicting_nested = ConfluencePageMetadata(
        page_id="nested",
        title="Different title",
        space_key="SPACE",
        ancestor_page_ids=("root",),
    )
    port = FakeInventoryPort(
        {
            "root": [root, nested],
            "nested": [conflicting_nested],
        }
    )

    with pytest.raises(ValueError, match="conflicting metadata"):
        BuildConfluenceInventory(inventory_port=port).execute(
            config=_config(root_ids=("root", "nested"))
        )


def test_excluded_subtree_items_remain_in_output() -> None:
    pages = [
        _page("root"),
        _page("skip", ancestors=("root",)),
        _page("under-skip", ancestors=("root", "skip")),
    ]
    port = FakeInventoryPort({"root": pages})

    items = BuildConfluenceInventory(inventory_port=port).execute(
        config=_config(excluded_ids=("skip",))
    )

    assert [item.scope_status for item in items] == [
        "included",
        "excluded_subtree",
        "excluded_subtree",
    ]
    assert items[1].scope_reason == "excluded_page:skip"
    assert items[2].scope_reason == "excluded_ancestor:skip"


def test_api_and_include_root_order_do_not_change_output() -> None:
    root = _page("root")
    nested = _page("nested", ancestors=("root",))
    leaf = _page("leaf", ancestors=("root", "nested"))
    first = FakeInventoryPort(
        {"root": [leaf, root, nested], "nested": [leaf, nested]}
    )
    second = FakeInventoryPort(
        {"root": [nested, leaf, root], "nested": [nested, leaf]}
    )

    first_items = BuildConfluenceInventory(inventory_port=first).execute(
        config=_config(root_ids=("root", "nested"), include_keywords=("travel",))
    )
    second_items = BuildConfluenceInventory(inventory_port=second).execute(
        config=_config(root_ids=("nested", "root"), exclude_keywords=("root",))
    )

    assert first_items == second_items


def test_output_sort_uses_structural_ids_not_titles() -> None:
    pages = [
        _page("root", title="Zulu"),
        _page("b", title="Alpha", ancestors=("root", "z-branch")),
        _page("a", title="Zulu", ancestors=("root", "a-branch")),
    ]
    port = FakeInventoryPort({"root": pages})

    items = BuildConfluenceInventory(inventory_port=port).execute(config=_config())

    assert [item.page_id for item in items] == ["root", "a", "b"]


def _config(
    *,
    root_ids: tuple[str, ...] = ("root",),
    excluded_ids: tuple[str, ...] = (),
    include_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
    page_size: int = 25,
) -> ConfluenceSourceConfig:
    return ConfluenceSourceConfig(
        source_id="wiki-poc",
        space_key="SPACE",
        include_roots=tuple(
            ConfluenceIncludeRoot(page_id=page_id) for page_id in root_ids
        ),
        exclude_subtrees=tuple(
            ConfluenceExcludeSubtree(page_id=page_id) for page_id in excluded_ids
        ),
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
        page_size=page_size,
    )


def _page(
    page_id: str,
    *,
    title: str | None = None,
    ancestors: tuple[str, ...] = (),
    parent: str | None = None,
    space: str = "SPACE",
    labels: tuple[str, ...] = (),
    attachment_count: int | None = None,
) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id=page_id,
        title=title or page_id,
        space_key=space,
        parent_page_id=parent,
        ancestor_page_ids=ancestors,
        ancestor_titles=tuple(f"Title {ancestor}" for ancestor in ancestors),
        labels=labels,
        attachment_count=attachment_count,
    )
