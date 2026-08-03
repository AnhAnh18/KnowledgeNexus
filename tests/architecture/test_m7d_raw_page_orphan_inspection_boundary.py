from __future__ import annotations

import ast
from pathlib import Path


_SOURCE = (
    Path(__file__).parents[2]
    / "src"
    / "knowledgenexus"
    / "foundation"
    / "infrastructure"
    / "raw_store"
    / "confluence_raw_page_orphan_inspector.py"
)


def _imports(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_m7d4a_inspector_has_no_live_or_mutating_dependencies() -> None:
    source = _SOURCE.read_text(encoding="utf-8")
    imports = _imports(source)

    assert not any(
        name.startswith(("urllib", "requests", "httpx", "socket"))
        for name in imports
    )
    assert not any(
        token in source
        for token in (
            "checkpoint",
            "budget",
            "lock",
            "attachment",
            "publish_page",
            "write_bytes",
            "unlink",
            "replace",
            "mkdir",
            "lambda",
            ".exists(",
            ".is_file(",
        )
    )


def test_m7d4a_inspector_uses_operation_specific_seam() -> None:
    source = _SOURCE.read_text(encoding="utf-8")

    assert "ConfluenceRawPageOrphanInspectionRequest" in source
    assert "ConfluenceRawPageOrphanInspectionResult" in source
    assert "inspect_raw_page" in source
