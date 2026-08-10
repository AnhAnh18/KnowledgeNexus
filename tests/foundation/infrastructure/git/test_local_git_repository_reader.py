from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from knowledgenexus.foundation.domain.models.git_code_source import (
    GitCasePolicy,
    GitCodeBuildError,
    GitCodeBuildFailureCategory,
    GitScanBudgets,
    GitSourceConfig,
)
from knowledgenexus.foundation.infrastructure.git.local_git_repository_reader import (
    GitCommandResult,
    LocalGitRepositoryReader,
)


def test_reader_rejects_malformed_runner_at_construction() -> None:
    with pytest.raises(TypeError):
        LocalGitRepositoryReader(runner=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LocalGitRepositoryReader(runner=False)  # type: ignore[arg-type]


COMMIT = "a" * 40
README_OID = "b" * 40
CPP_OID = "c" * 40
BIN_OID = "d" * 40


def _config(root: Path) -> GitSourceConfig:
    return GitSourceConfig(
        clone_root=root,
        repo_name="spen-sdk",
        branch="develop",
        commit_sha=COMMIT,
        crawled_at="2026-08-05T10:00:00Z",
        budgets=GitScanBudgets(
            max_tree_entries=100,
            max_file_bytes=1024,
            max_total_raw_bytes=4096,
            max_files=20,
            max_normalized_bytes=2048,
            max_in_memory_bytes=8192,
        ),
        case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
    )


class FakeRunner:
    def __init__(self, *, dirty: bool = False, bad_tree: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.dirty = dirty
        self.bad_tree = bad_tree

    def run(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path,
        stdin: bytes | None,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> GitCommandResult:
        self.calls.append(argv)
        if argv[:2] == ("rev-parse", "--verify"):
            return GitCommandResult(0, COMMIT.encode() + b"\n", b"")
        if argv[:2] == ("symbolic-ref", "--short"):
            return GitCommandResult(0, b"develop\n", b"")
        if argv[0] == "ls-tree":
            if self.bad_tree:
                return GitCommandResult(0, b"bad", b"")
            tree = (
                b"100644 blob " + README_OID.encode() + b"\tREADME.md\x00"
                b"100644 blob " + CPP_OID.encode() + b"\tsrc/main.cpp\x00"
                b"100644 blob " + BIN_OID.encode() + b"\tassets/image.png\x00"
            )
            return GitCommandResult(0, tree, b"")
        if argv[:2] == ("cat-file", "--batch-check"):
            ids = stdin.decode().splitlines() if stdin is not None else []
            sizes = {README_OID: 5, CPP_OID: 12, BIN_OID: 3}
            out = b"".join(
                f"{oid} blob {sizes[oid]}\n".encode("ascii") for oid in ids
            )
            return GitCommandResult(0, out, b"")
        if argv[:2] == ("cat-file", "--batch"):
            ids = stdin.decode().splitlines() if stdin is not None else []
            bodies = {README_OID: b"hello", CPP_OID: b"int main(){}"}
            out = b""
            for oid in ids:
                body = bodies[oid]
                out += f"{oid} blob {len(body)}\n".encode("ascii") + body + b"\n"
            return GitCommandResult(0, out, b"")
        raise AssertionError(argv)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "spen-sdk"
    root.mkdir()
    return root


def test_reader_uses_pinned_blob_bytes_and_excludes_binary(tmp_path: Path) -> None:
    runner = FakeRunner()
    snapshot = LocalGitRepositoryReader(runner=runner).read(config=_config(_root(tmp_path)))
    assert [item.path for item in snapshot.observations] == ["README.md", "src/main.cpp"]
    assert snapshot.observations[0].normalized_text == "hello"
    assert snapshot.observations[1].symbol_authority is True
    assert snapshot.metrics.excluded_binary == 1
    assert any(call[0] == "cat-file" for call in runner.calls)


def test_reader_rejects_malformed_tree_without_leaking_details(tmp_path: Path) -> None:
    with pytest.raises(GitCodeBuildError) as caught:
        LocalGitRepositoryReader(runner=FakeRunner(bad_tree=True)).read(config=_config(_root(tmp_path)))
    assert caught.value.category is GitCodeBuildFailureCategory.TREE_INVALID
    assert str(caught.value) == "tree_invalid"


def test_reader_rejects_casefold_collision(tmp_path: Path) -> None:
    runner = FakeRunner()

    class CollisionRunner:
        def run(self, **kwargs: object) -> GitCommandResult:
            result = runner.run(**kwargs)  # type: ignore[arg-type]
            argv = kwargs["argv"]
            if isinstance(argv, tuple) and argv[0] == "ls-tree":
                return GitCommandResult(
                    0,
                    (
                        b"100644 blob " + README_OID.encode() + b"\tREADME.md\x00"
                        b"100644 blob " + CPP_OID.encode() + b"\treadme.md\x00"
                    ),
                    b"",
                )
            return result

    with pytest.raises(GitCodeBuildError) as caught:
        LocalGitRepositoryReader(runner=CollisionRunner()).read(config=_config(_root(tmp_path)))
    assert caught.value.category is GitCodeBuildFailureCategory.PATH_COLLISION


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_subprocess_reader_is_bound_to_commit_not_dirty_worktree(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "README.md").write_text("committed", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "image.png").write_bytes(b"\x89PNG")

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    git("init", "-b", "develop")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "M9-B Test")
    git("add", ".")
    git("commit", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    config = _config(root)
    config = GitSourceConfig(
        clone_root=root,
        repo_name=config.repo_name,
        branch=config.branch,
        commit_sha=commit,
        crawled_at=config.crawled_at,
        budgets=config.budgets,
        case_policy=config.case_policy,
    )
    first = LocalGitRepositoryReader().read(config=config)
    (root / "README.md").write_text("dirty", encoding="utf-8")
    second = LocalGitRepositoryReader().read(config=config)
    assert first.observations[0].raw_bytes == b"committed"
    assert second.observations[0].raw_bytes == b"committed"
