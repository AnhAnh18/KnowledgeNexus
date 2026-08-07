from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli.accept_confluence_mini_corpus import (
    _load_selection,
    _safe_path,
)


def test_safe_path_rejects_relative_and_forbidden_paths() -> None:
    with pytest.raises(Exception):
        _safe_path("relative/path")
    with pytest.raises(Exception):
        _safe_path("C:/workspace/.local_ai/evidence")


def test_selection_loader_accepts_exact_sanitized_shape(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            [
                {
                    "page_id": str(1000 + index),
                    "crawled_at": "2026-08-05T00:00:00Z",
                    "expected_source_version": "1",
                }
                for index in range(10)
            ]
        ),
        encoding="utf-8",
    )
    items = _load_selection(path)
    assert len(items) == 10


def test_selection_loader_rejects_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            [
                {
                    "page_id": "1000",
                    "crawled_at": "2026-08-05T00:00:00Z",
                    "expected_source_version": "1",
                    "title": "must not be accepted",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        _load_selection(path)


def test_selection_loader_rejects_oversized_input_before_parse(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"
    path.write_text("[" + (" " * 131072) + "]", encoding="utf-8")
    with pytest.raises(Exception):
        _load_selection(path)


def test_safe_path_rejects_symlink_alias_to_forbidden_tree(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    forbidden = tmp_path / ".local_ai"
    forbidden.mkdir()
    alias = tmp_path / "alias"
    try:
        os.symlink(forbidden, alias, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(Exception):
        _safe_path(str(alias / "evidence"))


def test_safe_path_rejects_dangling_symlink_component(tmp_path: Path) -> None:
    alias = tmp_path / "dangling"
    try:
        os.symlink(tmp_path / "missing", alias)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(Exception):
        _safe_path(str(alias / "selection.json"))
