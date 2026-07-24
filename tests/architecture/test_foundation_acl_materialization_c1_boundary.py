from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_FOUNDATION = REPOSITORY_ROOT / "src" / "knowledgenexus" / "foundation"

_SIDECAR_MODULE = (
    _FOUNDATION
    / "infrastructure"
    / "sidecars"
    / "confluence_restriction_observation_sidecar.py"
)
_M6B_USE_CASE = (
    _FOUNDATION
    / "application"
    / "use_cases"
    / "collect_confluence_page_observations.py"
)
_M6B_CLI = (
    _FOUNDATION / "cli" / "collect_confluence_page_observations.py"
)

_FORBIDDEN_SIDECAR_IMPORT_PREFIXES = (
    "urllib",
    "requests",
    "httpx",
    "socket",
    "http",
    "ssl",
    "knowledgenexus.foundation.application",
    "knowledgenexus.foundation.cli",
    "knowledgenexus.foundation.domain",
    "knowledgenexus.foundation.infrastructure.confluence",
    "knowledgenexus.foundation.infrastructure.raw_store",
)

_OUT_OF_SCOPE_TOKENS = (
    "MaterializeConfluenceAcl",
    "ACLRecord",
    "extract_ordered_restriction_targets",
    "synthetic_fixture",
    "full_snapshot",
    "export",
    "persistence",
    "sidecar loader",
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


def test_sidecar_component_has_no_network_or_pipeline_dependency() -> None:
    imports = _imports(_SIDECAR_MODULE)

    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in _FORBIDDEN_SIDECAR_IMPORT_PREFIXES
    )


def test_m6b_use_case_remains_unaware_of_sidecar_capture() -> None:
    source = _M6B_USE_CASE.read_text(encoding="utf-8")

    assert "sidecar" not in source
    assert "filesystem" not in source
    assert "repository_root" not in source


def test_c1_cli_does_not_start_c2_acl_or_export_work() -> None:
    source = _M6B_CLI.read_text(encoding="utf-8")

    for token in _OUT_OF_SCOPE_TOKENS:
        assert token not in source
    assert "CollectConfluencePageObservations" in source
    assert "result.restriction_observations" in source


def test_only_cli_and_infrastructure_own_sidecar_responsibility() -> None:
    sidecar_mentions: list[Path] = []
    for layer in ("application", "domain", "ports"):
        root = _FOUNDATION / layer
        for path in root.rglob("*.py"):
            if "sidecar" in path.read_text(encoding="utf-8").lower():
                sidecar_mentions.append(path)

    assert sidecar_mentions == []
