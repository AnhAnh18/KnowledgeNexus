from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.git_code_source import (
    CodeDocumentPlan,
    GitCasePolicy,
    GitCodeBuildFailureCategory,
    GitCodeBuildResult,
    GitCodeBuildStatus,
    GitFileObservation,
    GitRepositorySnapshot,
    GitScanBudgets,
    GitScanMetrics,
    GitSourceConfig,
)


def _budgets() -> GitScanBudgets:
    return GitScanBudgets(
        max_tree_entries=100,
        max_file_bytes=1024,
        max_total_raw_bytes=4096,
        max_files=20,
        max_normalized_bytes=2048,
        max_in_memory_bytes=8192,
    )


def _config(root: Path) -> GitSourceConfig:
    return GitSourceConfig(
        clone_root=root,
        repo_name="spen-sdk",
        branch="develop",
        commit_sha="a" * 40,
        crawled_at="2026-08-05T10:00:00Z",
        budgets=_budgets(),
        case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
    )


def _observation(path: str = "README.md") -> GitFileObservation:
    return GitFileObservation(
        path=path,
        raw_bytes=b"hello",
        raw_byte_size=5,
        normalized_text="hello",
        normalized_byte_size=5,
        symbol_authority=False,
    )


def test_config_is_strict_and_runtime_validated(tmp_path: Path) -> None:
    root = tmp_path / "spen-sdk"
    root.mkdir()
    assert _config(root).commit_sha == "a" * 40
    with pytest.raises((TypeError, ValueError)):
        GitSourceConfig(  # type: ignore[arg-type]
            clone_root=object(),
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            crawled_at="2026-08-05T10:00:00Z",
            budgets=_budgets(),
            case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
        )
    with pytest.raises(TypeError):
        GitSourceConfig(  # type: ignore[arg-type]
            clone_root=root,
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            crawled_at="2026-08-05T10:00:00Z",
            budgets=_budgets(),
            case_policy="reject_casefold_collisions",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("path", ["../x", "/x", "a\\b", "a//b", "CON/x", "a/.", "a/.."])
def test_observation_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _observation(path)


def test_snapshot_cross_checks_metrics_and_owns_bytes() -> None:
    raw = bytearray(b"hello")
    observation = GitFileObservation(
        path="README.md",
        raw_bytes=bytes(raw),
        raw_byte_size=5,
        normalized_text="hello",
        normalized_byte_size=5,
        symbol_authority=False,
    )
    raw[0] = ord("X")
    snapshot = GitRepositorySnapshot(
        repo_name="spen-sdk",
        branch="develop",
        commit_sha="a" * 40,
        observations=(observation,),
        metrics=GitScanMetrics(
            seen=1,
            included=1,
            excluded_generated=0,
            excluded_vendor=0,
            excluded_binary=0,
            excluded_bytes=0,
            included_raw_bytes=5,
            included_normalized_bytes=5,
            included_chunk_count=0,
        ),
    )
    assert snapshot.observations[0].raw_bytes == b"hello"


def test_result_rejects_impossible_status_fields() -> None:
    with pytest.raises(ValueError):
        GitCodeBuildResult(
            status=GitCodeBuildStatus.SUCCESS,
            plan=None,
            error_category=None,
        )
    with pytest.raises(ValueError):
        GitCodeBuildResult(
            status=GitCodeBuildStatus.FAILED,
            plan=None,
            error_category=None,
        )


def test_plan_rejects_duplicate_chunk_ids() -> None:
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            observations=(),
            documents=(
                {
                    "document_id": "git:spen-sdk:README.md",
                },
            ),
            authority_observations=(),
            chunks=(
                {"chunk_id": "chunk:git:" + "a" * 16},
                {"chunk_id": "chunk:git:" + "a" * 16},
            ),
            metrics=GitScanMetrics(
                seen=1,
                included=1,
                excluded_generated=0,
                excluded_vendor=0,
                excluded_binary=0,
                excluded_bytes=0,
                included_raw_bytes=0,
                included_normalized_bytes=0,
                included_chunk_count=2,
            ),
        )
