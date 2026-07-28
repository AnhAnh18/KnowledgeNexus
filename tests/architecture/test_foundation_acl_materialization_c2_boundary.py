from __future__ import annotations

import ast
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases import (
    compose_confluence_acl,
    project_one_page_export,
)
from knowledgenexus.foundation.cli import materialize_confluence_acl as cli
from knowledgenexus.foundation.infrastructure.sidecars import (
    confluence_restriction_observation_sidecar as sidecar,
)

# M6G-B moves the C2 CLI's composition logic into compose_confluence_acl.py
# and adds project_one_page_export.py; both must uphold the same no-transport/
# no-credential/no-environment guarantees the CLI itself was already held to.
_GUARDED_MODULES = (cli, compose_confluence_acl, project_one_page_export)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", _GUARDED_MODULES, ids=lambda m: m.__name__)
def test_c2_boundary_module_imports_no_transport_connector_or_network_adapter(
    module: object,
) -> None:
    imports = _imports(Path(module.__file__))
    forbidden = (
        "confluence_http_transport",
        "confluence_data_center_inventory_adapter",
        "confluence_page_observation_adapter",
        "urllib",
        "http.client",
        "requests",
        "httpx",
        "socket",
    )

    assert not any(
        token in imported for imported in imports for token in forbidden
    )


@pytest.mark.parametrize("module", _GUARDED_MODULES, ids=lambda m: m.__name__)
def test_c2_boundary_module_reads_no_credentials_or_environment(
    module: object,
) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "CONFLUENCE_PAT",
        "CONFLUENCE_BASE_URL",
        "Authorization",
        "Bearer ",
        "os.environ",
        "os.getenv",
        "getenv(",
    ):
        assert forbidden not in source


def test_c2_loader_has_no_publish_or_network_dependency() -> None:
    imports = _imports(Path(sidecar.__file__))

    assert not any(
        token in imported
        for imported in imports
        for token in ("urllib", "http.client", "requests", "httpx", "socket")
    )
    source = Path(sidecar.__file__).read_text(encoding="utf-8")
    assert "MAX_RESTRICTION_SIDECAR_BYTES + 1" in source
    assert "Path.read_bytes" not in source
