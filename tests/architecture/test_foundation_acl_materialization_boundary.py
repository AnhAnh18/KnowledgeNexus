from __future__ import annotations

import ast
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    ProjectedPrincipal,
    ProjectedPrincipalUnion,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPOSITORY_ROOT / "src" / "knowledgenexus" / "foundation"

M6F_A_MODULES = (
    _SRC / "domain" / "models" / "acl_materialization.py",
    _SRC / "domain" / "rules" / "acl_relation_input_validator.py",
    _SRC / "domain" / "rules" / "acl_restriction_observations.py",
    _SRC / "domain" / "rules" / "acl_principal_projection.py",
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

# Out-of-scope work that M6F-A must not contain: ACLRecord construction, chunk
# ACL propagation, the C1 sidecar writer, and any credential/network handling.
_FORBIDDEN_SOURCE_TOKENS = (
    "ACLRecordBuilder",
    "acl_record_builder",
    "infrastructure",
    "sidecar",
    "CONFLUENCE_PAT",
    "Bearer",
    "requests",
    "urllib",
    'acl_tags"] =',
    ".acl_tags =",
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


@pytest.mark.parametrize("module", M6F_A_MODULES, ids=lambda p: p.name)
def test_module_has_no_infrastructure_network_or_filesystem_import(
    module: Path,
) -> None:
    imports = _imports(module)
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in _FORBIDDEN_IMPORT_PREFIXES
    )


@pytest.mark.parametrize("module", M6F_A_MODULES, ids=lambda p: p.name)
def test_module_source_has_no_out_of_scope_tokens(module: Path) -> None:
    source = module.read_text(encoding="utf-8")
    for token in _FORBIDDEN_SOURCE_TOKENS:
        assert token not in source, f"{module.name} unexpectedly contains {token!r}"


def test_projected_principal_repr_does_not_leak_source_values() -> None:
    principal = ProjectedPrincipal(
        namespace="user",
        source_representation="LEAK-SOURCE",
        canonical_identity="leak-source",
        acl_tag="user:leak-source",
    )
    union = ProjectedPrincipalUnion(users=(principal,), groups=())

    assert "LEAK-SOURCE" not in repr(principal)
    assert "leak-source" not in repr(principal)
    assert "LEAK" not in repr(union)


def test_error_str_carries_only_the_stable_category() -> None:
    error = AclMaterializationError(
        AclMaterializationFailureCategory.INVALID_RESTRICTION_OBSERVATIONS
    )

    assert str(error) == "invalid_restriction_observations"
