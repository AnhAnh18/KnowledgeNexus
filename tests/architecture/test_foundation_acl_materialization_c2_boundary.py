from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases import (
    compose_confluence_acl,
    project_one_page_export,
)
from knowledgenexus.foundation.cli import export_confluence_one_page_snapshot
from knowledgenexus.foundation.cli import materialize_confluence_acl as cli
from knowledgenexus.foundation.infrastructure.exporters import (
    one_page_full_snapshot_exporter,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    confluence_restriction_observation_sidecar as sidecar,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# M6G-B moves the C2 CLI's composition logic into compose_confluence_acl.py
# and adds project_one_page_export.py; both must uphold the same no-transport/
# no-credential/no-environment guarantees the CLI itself was already held to.
# M6G-C adds one_page_full_snapshot_exporter.py (the M3 orchestration boundary)
# and export_confluence_one_page_snapshot.py (the offline CLI), which must
# uphold the identical guarantees.
_GUARDED_MODULES = (
    cli,
    compose_confluence_acl,
    project_one_page_export,
    one_page_full_snapshot_exporter,
    export_confluence_one_page_snapshot,
)

# Files transferred/approved by M6G-B; M6G-C must not modify any of them.
_M6G_B_FILES = (
    "src/knowledgenexus/foundation/application/use_cases/compose_confluence_acl.py",
    "src/knowledgenexus/foundation/application/use_cases/project_one_page_export.py",
    "src/knowledgenexus/foundation/domain/models/confluence_acl_composition.py",
    "src/knowledgenexus/foundation/domain/models/one_page_export.py",
    "src/knowledgenexus/foundation/infrastructure/config/one_page_export_profile_loader.py",
)

# M3 exporter modules M6G-C reuses exactly and must never modify.
_M3_FILES = (
    "src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_writer.py",
    "src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_publisher.py",
    "src/knowledgenexus/foundation/domain/rules/dataset_version_generator.py",
)


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


# --- M6G-C: exporter + offline-CLI boundary ------------------------------------


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _call_dotted_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    if isinstance(func, ast.Name):
        return func.id
    return None


@pytest.mark.parametrize(
    "module",
    (one_page_full_snapshot_exporter, export_confluence_one_page_snapshot),
    ids=lambda m: m.__name__,
)
def test_m6g_c_module_never_reads_system_clock(module: object) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for call in _calls(tree):
        name = _call_dotted_name(call)
        if name in ("datetime.now", "datetime.utcnow", "time.time"):
            pytest.fail(f"{module.__name__} calls the system clock via {name}")


@pytest.mark.parametrize(
    "module",
    (one_page_full_snapshot_exporter, export_confluence_one_page_snapshot),
    ids=lambda m: m.__name__,
)
def test_m6g_c_module_references_no_m6g_d_or_m7_symbol(module: object) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for forbidden in (
        "m6g-d",
        "m6g_d",
        "tombstone_production",
        "delta_export",
        "sync_state_checkpoint",
        "qdrant",
        "embedding_index",
    ):
        assert forbidden not in source


def test_one_page_full_snapshot_exporter_imports_only_approved_m3_and_dataset_version_apis() -> (
    None
):
    imports = _imports(Path(one_page_full_snapshot_exporter.__file__))
    exporter_imports = {
        name
        for name in imports
        if name.startswith("knowledgenexus.foundation.infrastructure.exporters")
        or name.startswith("knowledgenexus.foundation.domain.rules")
    }
    assert exporter_imports == {
        "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher",
        "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer",
        "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer",
        "knowledgenexus.foundation.domain.rules.dataset_version_generator",
    }


def test_one_page_full_snapshot_exporter_never_writes_manifest_or_jsonl_content_directly() -> (
    None
):
    tree = ast.parse(
        Path(one_page_full_snapshot_exporter.__file__).read_text(encoding="utf-8")
    )
    for call in _calls(tree):
        name = _call_dotted_name(call)
        assert name != "json.dump"
        if name == "open":
            for keyword in call.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    assert "w" not in str(keyword.value.value)
    source = Path(one_page_full_snapshot_exporter.__file__).read_text(encoding="utf-8")
    assert ".write_text(" not in source
    assert ".write_bytes(" not in source


@pytest.mark.parametrize(
    "relative_path",
    _M6G_B_FILES + _M3_FILES,
)
def test_m6g_c_does_not_modify_m6g_b_or_m3_files(relative_path: str) -> None:
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", relative_path],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("git is not available to diff against HEAD in this environment")
    assert result.stdout.strip() == "", (
        f"{relative_path} has uncommitted changes; M6G-C must not modify "
        "M6G-B or M3 files"
    )
