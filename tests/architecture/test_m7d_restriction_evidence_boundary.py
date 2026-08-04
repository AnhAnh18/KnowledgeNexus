from __future__ import annotations

import ast
from pathlib import Path


def test_restriction_evidence_module_stays_in_domain_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    source_path = (
        root
        / "src"
        / "knowledgenexus"
        / "foundation"
        / "domain"
        / "models"
        / "confluence_restriction_evidence.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert all("foundation.infrastructure" not in name for name in imported_modules)
    assert all("foundation.application" not in name for name in imported_modules)
    assert all("foundation.ports" not in name for name in imported_modules)
