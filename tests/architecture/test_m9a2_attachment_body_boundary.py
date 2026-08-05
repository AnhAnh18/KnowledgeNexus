from __future__ import annotations

import ast
from pathlib import Path


_ROOT = (
    Path(__file__).parents[2]
    / "src"
    / "knowledgenexus"
    / "foundation"
)
_FILES = (
    _ROOT / "domain" / "models" / "media_body_materialization.py",
    _ROOT / "ports" / "confluence_attachment_body_fetch_port.py",
    _ROOT / "ports" / "confluence_raw_attachment_store_port.py",
    _ROOT / "application" / "use_cases" / "fetch_and_store_confluence_attachment_body.py",
    _ROOT / "infrastructure" / "raw_store" / "confluence_raw_attachment_store.py",
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


def test_m9a2_has_no_live_capture_or_downstream_storage_dependencies() -> None:
    for path in _FILES:
        source = path.read_text(encoding="utf-8")
        imports = _imports(source)
        assert not any(name.startswith(("urllib", "requests", "httpx", "socket")) for name in imports)
        assert not any(token in source for token in ("qdrant", "checkpoint", "ocr", "drawio"))


def test_m9a2_domain_and_ports_do_not_import_infrastructure() -> None:
    for path in _FILES[:3]:
        imports = _imports(path.read_text(encoding="utf-8"))
        assert not any(name.startswith("knowledgenexus.foundation.infrastructure") for name in imports)


def test_m9a2_store_does_not_use_replace_or_filename_path_components() -> None:
    source = (_ROOT / "infrastructure" / "raw_store" / "confluence_raw_attachment_store.py").read_text(
        encoding="utf-8"
    )
    assert "os.replace" not in source
    assert "envelope.filename" not in source
