from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Final, Sequence

from knowledgenexus.foundation.domain.models.confluence_inventory_item import (
    ConfluenceInventoryItem,
)


PAGES_INVENTORY_FILE_NAME: Final = "pages_inventory.jsonl"
INVENTORY_REPORT_FILE_NAME: Final = "inventory_report.csv"
CSV_COLUMNS: Final = (
    "source_id",
    "page_id",
    "title",
    "space_key",
    "parent_page_id",
    "page_path",
    "ancestor_page_ids",
    "ancestor_titles",
    "updated_at",
    "source_version",
    "labels",
    "attachment_count",
    "scope_status",
    "scope_reason",
)
CSV_FORMULA_PREFIXES: Final = ("=", "+", "-", "@")


class ConfluenceInventoryReportWriter:
    @staticmethod
    def write(
        *,
        output_dir: Path,
        items: Sequence[ConfluenceInventoryItem],
    ) -> int:
        if not output_dir.exists():
            raise FileNotFoundError(f"Output directory does not exist: {output_dir}")
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Output path is not a directory: {output_dir}")

        jsonl_path = output_dir / PAGES_INVENTORY_FILE_NAME
        csv_path = output_dir / INVENTORY_REPORT_FILE_NAME
        for target in (jsonl_path, csv_path):
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"Inventory report target already exists: {target}")

        materialized_items = tuple(items)
        jsonl_bytes = _render_jsonl(materialized_items)
        csv_bytes = _render_csv(materialized_items)

        temp_paths: list[Path] = []
        published_links: list[tuple[Path, Path]] = []
        try:
            jsonl_temp = _write_temp_file(jsonl_path, jsonl_bytes)
            temp_paths.append(jsonl_temp)
            csv_temp = _write_temp_file(csv_path, csv_bytes)
            temp_paths.append(csv_temp)

            _publish_no_clobber(temp_path=jsonl_temp, target_path=jsonl_path)
            published_links.append((jsonl_path, jsonl_temp))
            _publish_no_clobber(temp_path=csv_temp, target_path=csv_path)
            published_links.append((csv_path, csv_temp))

            for temp_path in temp_paths:
                _remove_owned_file(temp_path)
            temp_paths.clear()
        except Exception:
            for target_path, temp_path in reversed(published_links):
                _remove_owned_link(target_path=target_path, temp_path=temp_path)
            for temp_path in temp_paths:
                _remove_owned_file(temp_path)
            raise

        return len(materialized_items)


def _render_jsonl(items: Sequence[ConfluenceInventoryItem]) -> bytes:
    lines = []
    for item in items:
        record = asdict(item)
        record["page_path"] = _page_path(item)
        lines.append(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    output = "" if not lines else "\n".join(lines) + "\n"
    return output.encode("utf-8")


def _render_csv(items: Sequence[ConfluenceInventoryItem]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                "source_id": _csv_scalar(item.source_id),
                "page_id": _csv_scalar(item.page_id),
                "title": _csv_scalar(item.title),
                "space_key": _csv_scalar(item.space_key),
                "parent_page_id": _csv_scalar(item.parent_page_id),
                "page_path": _csv_scalar(_page_path(item)),
                "ancestor_page_ids": _compact_json_array(item.ancestor_page_ids),
                "ancestor_titles": _compact_json_array(item.ancestor_titles),
                "updated_at": _csv_scalar(item.updated_at),
                "source_version": _csv_scalar(item.source_version),
                "labels": _compact_json_array(item.labels),
                "attachment_count": _csv_scalar(item.attachment_count),
                "scope_status": _csv_scalar(item.scope_status),
                "scope_reason": _csv_scalar(item.scope_reason),
            }
        )
    return output.getvalue().encode("utf-8")


def _write_temp_file(target: Path, content: bytes) -> Path:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
        return temp_path
    except Exception:
        if temp_path is not None:
            _remove_owned_file(temp_path)
        raise


def _publish_no_clobber(*, temp_path: Path, target_path: Path) -> None:
    os.link(temp_path, target_path)


def _page_path(item: ConfluenceInventoryItem) -> str:
    return " / ".join((*item.ancestor_titles, item.title))


def _compact_json_array(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _csv_scalar(value: object | None) -> object:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_owned_link(*, target_path: Path, temp_path: Path) -> None:
    try:
        if (
            target_path.exists()
            and temp_path.exists()
            and target_path.samefile(temp_path)
        ):
            target_path.unlink()
    except OSError:
        pass
