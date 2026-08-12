from __future__ import annotations

import ast
from pathlib import Path


_ROOT = Path(__file__).parents[2] / "src" / "knowledgenexus" / "foundation"
_TARGETS = (
    _ROOT / "domain" / "models" / "media_processing.py",
    _ROOT / "domain" / "models" / "drawio_xml.py",
    _ROOT / "ports" / "media_processing_port.py",
    _ROOT / "infrastructure" / "processors" / "drawio_xml_processor.py",
    _ROOT / "infrastructure" / "processors" / "media_attachment_processors.py",
)
_FORBIDDEN_IMPORTS = {
    "fitz",
    "pdfplumber",
    "pytesseract",
    "PIL",
    "subprocess",
    "requests",
    "httpx",
    "socket",
    "urllib.request",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def test_m9a3_processors_have_no_engine_network_or_process_imports() -> None:
    for path in _TARGETS:
        assert _imports(path).isdisjoint(_FORBIDDEN_IMPORTS), path.name


def test_m9a3_processing_seam_has_no_file_or_network_side_effect_calls() -> None:
    forbidden_tokens = (
        "open(",
        "write_text(",
        "write_bytes(",
        "unlink(",
        "requests.",
        "httpx.",
        "subprocess.",
        "socket.",
    )
    for path in _TARGETS:
        source = path.read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden_tokens), path.name
