from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import BinaryIO

import pytest

from knowledgenexus.foundation.domain.models import ConfluenceInventoryItem
from knowledgenexus.foundation.infrastructure.exporters.confluence_inventory_report_writer import (
    ConfluenceInventoryReportWriter,
)


def test_writes_exact_deterministic_jsonl_and_csv_bytes(tmp_path: Path) -> None:
    items = (
        _item(
            page_id="page-1",
            title='Thiết kế, "API"',
            ancestors=("root", "parent"),
            ancestor_titles=("Gốc", "Nhánh"),
            labels=("api", "design"),
            attachment_count=None,
        ),
        _item(
            page_id="page-2",
            title="Empty attachments",
            attachment_count=0,
            scope_status="excluded_subtree",
            scope_reason="excluded_page:page-2",
        ),
    )

    count = ConfluenceInventoryReportWriter.write(output_dir=tmp_path, items=items)

    assert count == 2
    jsonl_bytes = (tmp_path / "pages_inventory.jsonl").read_bytes()
    assert jsonl_bytes == (
        '{"ancestor_page_ids":["root","parent"],"ancestor_titles":["Gốc","Nhánh"],'
        '"attachment_count":null,"labels":["api","design"],"page_id":"page-1",'
        '"page_path":"Gốc / Nhánh / Thiết kế, \\"API\\"","parent_page_id":null,'
        '"scope_reason":"included_descendant","scope_status":"included",'
        '"source_id":"wiki-poc","source_version":null,"space_key":"SPACE",'
        '"title":"Thiết kế, \\"API\\"","updated_at":null}\n'
        '{"ancestor_page_ids":[],"ancestor_titles":[],"attachment_count":0,'
        '"labels":[],"page_id":"page-2","page_path":"Empty attachments",'
        '"parent_page_id":null,"scope_reason":"excluded_page:page-2",'
        '"scope_status":"excluded_subtree","source_id":"wiki-poc",'
        '"source_version":null,"space_key":"SPACE","title":"Empty attachments",'
        '"updated_at":null}\n'
    ).encode("utf-8")

    csv_bytes = (tmp_path / "inventory_report.csv").read_bytes()
    assert csv_bytes == (
        "source_id,page_id,title,space_key,parent_page_id,page_path,"
        "ancestor_page_ids,ancestor_titles,updated_at,source_version,labels,"
        "attachment_count,scope_status,scope_reason\n"
        'wiki-poc,page-1,"Thiết kế, ""API""",SPACE,,"Gốc / Nhánh / Thiết kế, '
        '""API""","[""root"",""parent""]","[""Gốc"",""Nhánh""]",'
        ',,"[""api"",""design""]",,included,included_descendant\n'
        "wiki-poc,page-2,Empty attachments,SPACE,,Empty attachments,[],[],"
        ",,[],0,excluded_subtree,excluded_page:page-2\n"
    ).encode("utf-8")
    assert b"\r\n" not in csv_bytes
    assert not jsonl_bytes.startswith(b"\xef\xbb\xbf")
    assert not csv_bytes.startswith(b"\xef\xbb\xbf")


def test_empty_items_write_zero_byte_jsonl_and_header_only_csv(
    tmp_path: Path,
) -> None:
    count = ConfluenceInventoryReportWriter.write(output_dir=tmp_path, items=())

    assert count == 0
    assert (tmp_path / "pages_inventory.jsonl").read_bytes() == b""
    assert (tmp_path / "inventory_report.csv").read_text(encoding="utf-8") == (
        "source_id,page_id,title,space_key,parent_page_id,page_path,"
        "ancestor_page_ids,ancestor_titles,updated_at,source_version,labels,"
        "attachment_count,scope_status,scope_reason\n"
    )


def test_independent_output_directories_have_identical_bytes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    items = (_item(page_id="unicode", title="Tiếng Việt"),)

    ConfluenceInventoryReportWriter.write(output_dir=first, items=items)
    ConfluenceInventoryReportWriter.write(output_dir=second, items=items)

    for name in ("pages_inventory.jsonl", "inventory_report.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert "Tiếng Việt" in (first / "pages_inventory.jsonl").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("target_name", ["pages_inventory.jsonl", "inventory_report.csv"])
def test_pre_existing_target_is_not_overwritten(
    tmp_path: Path,
    target_name: str,
) -> None:
    target = tmp_path / target_name
    target.write_bytes(b"owned by caller")

    with pytest.raises(FileExistsError):
        ConfluenceInventoryReportWriter.write(
            output_dir=tmp_path,
            items=(_item(page_id="page"),),
        )

    assert target.read_bytes() == b"owned by caller"
    assert sorted(path.name for path in tmp_path.iterdir()) == [target_name]


def test_missing_output_directory_is_not_created(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing"

    with pytest.raises(FileNotFoundError):
        ConfluenceInventoryReportWriter.write(output_dir=output_dir, items=())

    assert not output_dir.exists()


def test_publish_failure_propagates_and_removes_owned_outputs_and_temps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledgenexus.foundation.infrastructure.exporters import (
        confluence_inventory_report_writer as writer_module,
    )

    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"preserve")
    original_link = writer_module.os.link

    def fail_csv_link(source: Path, target: Path) -> None:
        if Path(target).name == "inventory_report.csv":
            raise OSError("simulated publish failure")
        original_link(source, target)

    monkeypatch.setattr(writer_module.os, "link", fail_csv_link)

    with pytest.raises(OSError, match="simulated publish failure"):
        ConfluenceInventoryReportWriter.write(
            output_dir=tmp_path,
            items=(_item(page_id="page"),),
        )

    assert unrelated.read_bytes() == b"preserve"
    assert not (tmp_path / "pages_inventory.jsonl").exists()
    assert not (tmp_path / "inventory_report.csv").exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_concurrent_creator_cannot_be_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledgenexus.foundation.infrastructure.exporters import (
        confluence_inventory_report_writer as writer_module,
    )

    concurrent_bytes = b"created by concurrent writer"
    original_link = writer_module.os.link

    def create_target_then_link(source: Path, target: Path) -> None:
        target_path = Path(target)
        if target_path.name == "pages_inventory.jsonl":
            target_path.write_bytes(concurrent_bytes)
        original_link(source, target)

    monkeypatch.setattr(writer_module.os, "link", create_target_then_link)

    with pytest.raises(FileExistsError):
        ConfluenceInventoryReportWriter.write(
            output_dir=tmp_path,
            items=(_item(page_id="page"),),
        )

    assert (tmp_path / "pages_inventory.jsonl").read_bytes() == concurrent_bytes
    assert not (tmp_path / "inventory_report.csv").exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_temp_write_failure_propagates_and_removes_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledgenexus.foundation.infrastructure.exporters import (
        confluence_inventory_report_writer as writer_module,
    )

    real_named_temporary_file = writer_module.tempfile.NamedTemporaryFile

    class FailingTemporaryFile:
        def __init__(self, wrapped: BinaryIO) -> None:
            self._wrapped = wrapped
            self.name = wrapped.name

        def __enter__(self) -> FailingTemporaryFile:
            self._wrapped.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._wrapped.__exit__(*args)

        def write(self, content: bytes) -> int:
            self._wrapped.write(content[:1])
            raise OSError("simulated temp write failure")

    def failing_named_temporary_file(*args: object, **kwargs: object) -> object:
        return FailingTemporaryFile(real_named_temporary_file(*args, **kwargs))

    monkeypatch.setattr(
        writer_module.tempfile,
        "NamedTemporaryFile",
        failing_named_temporary_file,
    )

    with pytest.raises(OSError, match="simulated temp write failure"):
        ConfluenceInventoryReportWriter.write(
            output_dir=tmp_path,
            items=(_item(page_id="page"),),
        )

    assert list(tmp_path.iterdir()) == []


def test_csv_formula_prefixes_are_neutralized_but_jsonl_values_are_unchanged(
    tmp_path: Path,
) -> None:
    dangerous_titles = ("=1+1", "+SUM(A1:A2)", "-2+3", "@command")
    items = tuple(
        _item(page_id=f"page-{index}", title=title)
        for index, title in enumerate(dangerous_titles)
    )

    ConfluenceInventoryReportWriter.write(output_dir=tmp_path, items=items)

    with (tmp_path / "inventory_report.csv").open(
        "r", encoding="utf-8", newline=""
    ) as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    json_rows = [
        json.loads(line)
        for line in (tmp_path / "pages_inventory.jsonl").read_text("utf-8").splitlines()
    ]

    assert [row["title"] for row in csv_rows] == [
        f"'{title}" for title in dangerous_titles
    ]
    assert [row["page_path"] for row in csv_rows] == [
        f"'{title}" for title in dangerous_titles
    ]
    assert [row["title"] for row in json_rows] == list(dangerous_titles)
    assert [row["page_path"] for row in json_rows] == list(dangerous_titles)


def test_output_contains_no_connection_or_environment_values(tmp_path: Path) -> None:
    ConfluenceInventoryReportWriter.write(
        output_dir=tmp_path,
        items=(_item(page_id="page"),),
    )

    output = b"".join(path.read_bytes() for path in tmp_path.iterdir())
    assert b"PAT" not in output
    assert b"base_url" not in output
    assert str(tmp_path).encode("utf-8") not in output
    assert json.loads((tmp_path / "pages_inventory.jsonl").read_text("utf-8"))[
        "attachment_count"
    ] is None


def _item(
    *,
    page_id: str,
    title: str | None = None,
    ancestors: tuple[str, ...] = (),
    ancestor_titles: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    attachment_count: int | None = None,
    scope_status: str = "included",
    scope_reason: str = "included_descendant",
) -> ConfluenceInventoryItem:
    return ConfluenceInventoryItem(
        source_id="wiki-poc",
        page_id=page_id,
        title=title or page_id,
        space_key="SPACE",
        parent_page_id=None,
        ancestor_page_ids=ancestors,
        ancestor_titles=ancestor_titles,
        updated_at=None,
        source_version=None,
        labels=labels,
        attachment_count=attachment_count,
        scope_status=scope_status,  # type: ignore[arg-type]
        scope_reason=scope_reason,
    )
