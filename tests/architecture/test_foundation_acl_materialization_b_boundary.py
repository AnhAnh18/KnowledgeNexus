from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPOSITORY_ROOT / "src" / "knowledgenexus" / "foundation"

# M6F-B production modules: the use case and its result/quality models. Unlike
# M6F-A, these legitimately build an ``ACLRecord`` and set ``acl_tags``; the
# boundary they must still respect is no filesystem, network, credential,
# group-resolution, sidecar/CLI, or exporter/tombstone behavior.
M6F_B_MODULES = (
    _SRC / "application" / "use_cases" / "materialize_confluence_acl.py",
    _SRC / "domain" / "models" / "acl_materialization_result.py",
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "urllib",
    "requests",
    "httpx",
    "socket",
    "http",
    "ssl",
    "os",
    "pathlib",
    "knowledgenexus.foundation.infrastructure",
    "knowledgenexus.foundation.cli",
)

# Out-of-scope work M6F-B must not contain: any network/credential handling, the
# C1 sidecar writer, group membership expansion, exporter/tombstone/M6G export.
_FORBIDDEN_SOURCE_TOKENS = (
    "urllib",
    "requests",
    "httpx",
    "socket",
    "CONFLUENCE_PAT",
    "Bearer",
    "sidecar",
    "membership",
    "tombstone",
    "exporter",
    "infrastructure",
    "open(",
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


@pytest.mark.parametrize("module", M6F_B_MODULES, ids=lambda p: p.name)
def test_module_has_no_infrastructure_network_or_filesystem_import(
    module: Path,
) -> None:
    imports = _imports(module)
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in _FORBIDDEN_IMPORT_PREFIXES
    )


@pytest.mark.parametrize("module", M6F_B_MODULES, ids=lambda p: p.name)
def test_module_source_has_no_out_of_scope_tokens(module: Path) -> None:
    source = module.read_text(encoding="utf-8")
    for token in _FORBIDDEN_SOURCE_TOKENS:
        assert token not in source, f"{module.name} unexpectedly contains {token!r}"


def test_use_case_reuses_the_existing_acl_record_builder() -> None:
    source = (
        _SRC / "application" / "use_cases" / "materialize_confluence_acl.py"
    ).read_text(encoding="utf-8")
    # M6F-B is the stage that legitimately builds the record and sets tags.
    assert "ACLRecordBuilder" in source
    assert "acl_tags" in source
    # It must not define a second builder or a parallel error/enum type.
    assert "class ACLRecordBuilder" not in source
    assert "class AclMaterializationError" not in source
    assert "StrEnum" not in source
