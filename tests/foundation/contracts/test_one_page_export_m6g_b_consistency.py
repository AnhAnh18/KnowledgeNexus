"""M6G-B contract-consistency checks that go beyond Markdown substrings.

These guard structural guarantees from the M6G-B task contract that a plain
unit test on one module would not catch on its own: no M3 exporter reuse
anywhere in the new M6G-B code, no leftover private composition symbols on
the refactored C2 CLI, the deliberate empty-tuple (never fabricated) deferred
streams, and the domain/models import-cycle avoidance for
``one_page_export.py`` (R11) proven by an actual cold import in both orders.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases import (
    compose_confluence_acl,
    project_one_page_export,
)
from knowledgenexus.foundation.cli import materialize_confluence_acl as cli

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src"

_M3_EXPORT_SYMBOLS = (
    "FullSnapshotStagingWriter",
    "FullSnapshotStagingCompleter",
    "FullSnapshotPublisher",
    "DatasetVersionGenerator",
)
_M3_EXPORT_MODULE_MARKERS = (
    "full_snapshot_staging_writer",
    "full_snapshot_staging_completer",
    "full_snapshot_publisher",
    "dataset_version_generator",
)
_M6G_B_MODULES = (cli, compose_confluence_acl, project_one_page_export)


def _module_source(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _imported_module_names(module: object) -> set[str]:
    tree = ast.parse(_module_source(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", _M6G_B_MODULES, ids=lambda m: m.__name__)
def test_no_m3_exporter_import_or_reference_in_m6g_b_code(module: object) -> None:
    imports = _imported_module_names(module)
    assert not any(
        marker in imported
        for imported in imports
        for marker in _M3_EXPORT_MODULE_MARKERS
    )
    source = _module_source(module)
    for symbol in _M3_EXPORT_SYMBOLS:
        assert symbol not in source


def test_c2_cli_no_longer_owns_private_composition_helpers() -> None:
    for name in (
        "_FixedRawPageReader",
        "_bind_restriction_ancestry",
        "_compose_once",
        "_Composition",
    ):
        assert not hasattr(cli, name), (
            f"{name} should have moved to ComposeConfluenceAcl, not stayed "
            "on the CLI"
        )
    assert hasattr(cli, "ComposeConfluenceAcl")


def test_compose_confluence_acl_module_owns_the_composition_helpers() -> None:
    assert hasattr(compose_confluence_acl, "_FixedRawPageReader")
    assert hasattr(compose_confluence_acl, "_bind_restriction_ancestry")
    assert hasattr(compose_confluence_acl, "ComposeConfluenceAcl")


def test_projection_source_never_fabricates_deferred_stream_records() -> None:
    source = _module_source(project_one_page_export)
    for field_name in ("media_assets", "symbols", "sync_state", "tombstones"):
        assert f"{field_name}=()" in source


def test_one_page_export_is_not_re_exported_from_domain_models_package() -> None:
    import knowledgenexus.foundation.domain.models as domain_models

    assert "OnePageExportProfileBundle" not in vars(domain_models)
    assert "OnePageExportProfileBundle" not in domain_models.__all__
    assert "one_page_export" not in domain_models.__all__


def _run_isolated_import(script: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC_ROOT)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_one_page_export_importable_after_domain_rules_in_a_fresh_process() -> None:
    # domain/rules/__init__.py eagerly imports wiki_structure_parser, which
    # imports domain.models.* -- proving one_page_export.py still imports
    # cleanly afterward is the actual regression guard for R11, not just an
    # assumption.
    script = (
        "import knowledgenexus.foundation.domain.rules\n"
        "import knowledgenexus.foundation.domain.models.one_page_export as m\n"
        "assert hasattr(m, 'OnePageExportProfileBundle')\n"
    )
    result = _run_isolated_import(script)
    assert result.returncode == 0, result.stderr


def test_one_page_export_importable_before_domain_rules_in_a_fresh_process() -> None:
    script = (
        "import knowledgenexus.foundation.domain.models.one_page_export as m\n"
        "import knowledgenexus.foundation.domain.rules\n"
        "assert hasattr(m, 'OnePageExportProfileBundle')\n"
    )
    result = _run_isolated_import(script)
    assert result.returncode == 0, result.stderr
