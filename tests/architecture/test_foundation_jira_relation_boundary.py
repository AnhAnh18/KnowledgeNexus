from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
USE_CASE = (
    REPOSITORY_ROOT
    / "src"
    / "knowledgenexus"
    / "foundation"
    / "application"
    / "use_cases"
    / "build_confluence_jira_relations.py"
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_m6e_use_case_has_no_network_raw_jira_or_infrastructure_dependency() -> None:
    imports = _imports(USE_CASE)
    forbidden = (
        "urllib",
        "requests",
        "httpx",
        "socket",
        "knowledgenexus.foundation.infrastructure",
    )

    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in forbidden
    )


def test_m6e_source_does_not_add_out_of_scope_relation_or_acl_work() -> None:
    source = USE_CASE.read_text(encoding="utf-8")

    for forbidden in (
        "embeds_media",
        "includes_page",
        "links_to_page",
        "AclRecord",
        "jira_pat",
        "body.storage",
        "storage_xhtml",
    ):
        assert forbidden not in source
