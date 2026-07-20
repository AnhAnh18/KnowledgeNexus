from __future__ import annotations

import ast
from pathlib import Path

import pytest

# D34 / CODEX_CODING_RULES: application code depends on ports and domain rules,
# never on concrete infrastructure. This is a minimal import-linter equivalent.
_SRC = Path(__file__).resolve().parents[2] / "src"
_USE_CASES = _SRC / "knowledgenexus" / "foundation" / "application" / "use_cases"
_FORBIDDEN_PREFIX = "knowledgenexus.foundation.infrastructure"


def _use_case_modules() -> list[Path]:
    return sorted(
        p for p in _USE_CASES.glob("*.py") if p.name != "__init__.py"
    )


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_use_case_directory_is_present() -> None:
    assert _use_case_modules(), "expected at least one application use case"


@pytest.mark.parametrize(
    "module_path",
    _use_case_modules(),
    ids=lambda p: p.name,
)
def test_application_use_case_does_not_import_infrastructure(
    module_path: Path,
) -> None:
    imported = _imported_modules(module_path.read_text(encoding="utf-8"))
    offenders = sorted(
        name for name in imported if name.startswith(_FORBIDDEN_PREFIX)
    )
    assert offenders == [], (
        f"{module_path.name} imports infrastructure directly: {offenders}. "
        "Depend on foundation.ports and foundation.domain instead."
    )
