from __future__ import annotations

import ast
from pathlib import Path


def test_m7d_restriction_store_does_not_import_m6_sidecar_or_application() -> None:
    root = Path(__file__).resolve().parents[2]
    source_path = (
        root
        / "src"
        / "knowledgenexus"
        / "foundation"
        / "infrastructure"
        / "raw_store"
        / "confluence_raw_restriction_store.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert all("foundation.infrastructure.sidecars" not in name for name in imported_modules)
    assert all("foundation.application" not in name for name in imported_modules)
