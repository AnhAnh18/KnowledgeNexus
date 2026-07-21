from __future__ import annotations

import ast
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "knowledgenexus"
FOUNDATION_ROOT = SRC_ROOT / "foundation"
TOKENIZATION_INFRASTRUCTURE = FOUNDATION_ROOT / "infrastructure" / "tokenization"


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module)
    return imports


def test_foundation_domain_and_application_do_not_import_tokenizer_libraries() -> None:
    forbidden = (
        "tokenizers",
        "transformers",
        "huggingface_hub",
        "FlagEmbedding",
        "sentencepiece",
    )
    for root in (FOUNDATION_ROOT / "domain", FOUNDATION_ROOT / "application"):
        for path in sorted(root.rglob("*.py")):
            imports = _absolute_imports(path)
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in imports
                for prefix in forbidden
            ), f"forbidden tokenizer dependency in {path.name}: {sorted(imports)}"


def test_foundation_tokenizer_infrastructure_does_not_import_indexing_or_inference() -> None:
    forbidden = (
        "knowledgenexus.indexing",
        "transformers",
        "huggingface_hub",
        "FlagEmbedding",
        "sentencepiece",
        "torch",
    )
    imports = set()
    for path in sorted(TOKENIZATION_INFRASTRUCTURE.rglob("*.py")):
        imports.update(_absolute_imports(path))

    assert "tokenizers" in imports
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imports
        for prefix in forbidden
    )
