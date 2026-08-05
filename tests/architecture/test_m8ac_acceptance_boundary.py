from __future__ import annotations

import ast
from pathlib import Path


_ROOT = Path(__file__).parents[2] / "src" / "knowledgenexus" / "foundation"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_m8ac_has_no_network_or_downstream_storage_imports() -> None:
    for path in (
        _ROOT / "domain" / "models" / "confluence_mini_corpus_acceptance.py",
        _ROOT / "application" / "use_cases" / "accept_confluence_mini_corpus.py",
        _ROOT / "cli" / "accept_confluence_mini_corpus.py",
    ):
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        assert not any(name.startswith(("urllib", "requests", "httpx", "socket")) for name in imports)
        assert "qdrant" not in source.lower()
        assert "export" not in source.lower()
        assert "checkpoint" not in source.lower()


def test_m8ac_summary_has_an_allowlisted_aggregate_surface() -> None:
    source = (_ROOT / "domain" / "models" / "confluence_mini_corpus_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "page_id" not in source.split("class MiniCorpusAcceptanceSummary", 1)[1]
    assert "body_bytes" not in source.split("class MiniCorpusAcceptanceSummary", 1)[1]
