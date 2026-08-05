from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_APPLICATION = (
    _ROOT
    / "src"
    / "knowledgenexus"
    / "foundation"
    / "application"
    / "use_cases"
    / "build_git_code_documents.py"
)
_DOMAIN = _ROOT / "src" / "knowledgenexus" / "foundation" / "domain" / "models" / "git_code_source.py"
_READER = (
    _ROOT
    / "src"
    / "knowledgenexus"
    / "foundation"
    / "infrastructure"
    / "git"
    / "local_git_repository_reader.py"
)


def test_m9b_application_has_no_infrastructure_or_downstream_imports() -> None:
    source = _APPLICATION.read_text(encoding="utf-8")
    forbidden = (
        "foundation.infrastructure",
        "requests",
        "httpx",
        "qdrant",
        "embedding",
        "raw_store",
        "checkpoint",
        "export",
    )
    assert not any(token in source for token in forbidden)


def test_m9b_domain_has_no_io_or_infrastructure_imports() -> None:
    source = _DOMAIN.read_text(encoding="utf-8")
    forbidden = ("subprocess", "socket", "urllib", "foundation.infrastructure", "raw_store")
    assert not any(token in source for token in forbidden)


def test_m9b_reader_has_no_network_or_mutating_git_commands() -> None:
    source = _READER.read_text(encoding="utf-8")
    forbidden_argv = (
        '"clone"',
        '"fetch"',
        '"push"',
        '"pull"',
        '"remote"',
    )
    assert not any(token in source for token in forbidden_argv)
