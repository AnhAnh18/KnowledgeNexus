from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

from knowledgenexus.foundation.application.use_cases import BuildConfluenceInventory
from knowledgenexus.foundation.domain.models import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluencePageMetadata,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.exporters.confluence_inventory_report_writer import (
    ConfluenceInventoryReportWriter,
)


class SyntheticInventoryPort:
    def __init__(self, *, reverse_order: bool) -> None:
        root = _page("root")
        nested = _page("nested", ancestors=("root",), attachment_count=None)
        excluded = _page("excluded", ancestors=("root", "nested"))
        leaf = _page("leaf", ancestors=("root", "nested", "excluded"))
        pages = {
            "root": [root, nested, excluded, leaf],
            "nested": [nested, excluded, leaf],
        }
        self._pages = {
            key: tuple(reversed(value)) if reverse_order else tuple(value)
            for key, value in pages.items()
        }

    def iter_page_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterable[ConfluencePageMetadata]:
        return iter(self._pages[root_page_id])


def test_fake_port_to_reports_preserves_included_and_excluded_audit_rows(
    tmp_path: Path,
) -> None:
    config = ConfluenceSourceConfig(
        source_id="synthetic-wiki",
        space_key="SPACE",
        include_roots=(
            ConfluenceIncludeRoot(page_id="nested"),
            ConfluenceIncludeRoot(page_id="root"),
        ),
        exclude_subtrees=(ConfluenceExcludeSubtree(page_id="excluded"),),
        page_size=5,
    )
    use_case = BuildConfluenceInventory(
        inventory_port=SyntheticInventoryPort(reverse_order=True)
    )

    items = use_case.execute(config=config)
    count = ConfluenceInventoryReportWriter.write(output_dir=tmp_path, items=items)

    json_rows = [
        json.loads(line)
        for line in (tmp_path / "pages_inventory.jsonl").read_text("utf-8").splitlines()
    ]
    with (tmp_path / "inventory_report.csv").open(
        "r", encoding="utf-8", newline=""
    ) as csv_file:
        csv_rows = list(csv.DictReader(csv_file))

    assert count == 4
    assert [row["page_id"] for row in json_rows] == [
        "root",
        "nested",
        "excluded",
        "leaf",
    ]
    assert [row["scope_status"] for row in json_rows] == [
        "included",
        "included",
        "excluded_subtree",
        "excluded_subtree",
    ]
    assert json_rows[1]["attachment_count"] is None
    assert [row["scope_reason"] for row in csv_rows[-2:]] == [
        "excluded_page:excluded",
        "excluded_ancestor:excluded",
    ]


def _page(
    page_id: str,
    *,
    ancestors: tuple[str, ...] = (),
    attachment_count: int | None = 0,
) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id=page_id,
        title=f"Title {page_id}",
        space_key="SPACE",
        ancestor_page_ids=ancestors,
        ancestor_titles=tuple(f"Title {ancestor}" for ancestor in ancestors),
        attachment_count=attachment_count,
    )
