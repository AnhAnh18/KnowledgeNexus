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
    / "confluence_raw_page_generation_store.py"
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


def test_m7d_raw_page_store_has_no_live_or_checkpoint_dependencies() -> None:
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
            "attachment",
            "ConfluenceRawPageStore(",
            "lambda",
        )
    )


def test_m7d_raw_page_store_does_not_import_m6_fixed_path_store() -> None:
    imports = _imports(_SOURCE.read_text(encoding="utf-8"))
    assert "knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_store" not in imports
