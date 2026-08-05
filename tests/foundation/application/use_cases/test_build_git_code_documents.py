from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from knowledgenexus.foundation.application.use_cases.build_git_code_documents import (
    BuildGitCodeDocuments,
    BuildGitCodeDocumentsRequest,
)
from knowledgenexus.foundation.domain.models import (
    CharacterSpan,
    CodeDocumentPlan,
    ChunkingProfile,
    GitCasePolicy,
    GitCodeBuildFailureCategory,
    GitCodeBuildStatus,
    GitFileObservation,
    GitRepositorySnapshot,
    GitScanBudgets,
    GitScanMetrics,
    GitSourceConfig,
    TokenizationResult,
    TokenizerAsset,
)
from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


def _profile() -> ChunkingProfile:
    revision = "5617a9f61b028005a4858fdac845db406aefb181"
    repository = "https://huggingface.co/BAAI/bge-m3"
    return ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=96,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository=repository,
        tokenizer_revision=revision,
        observed_license="MIT",
        provenance_url=f"{repository}/tree/{revision}",
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17_098_108,
                sha256="21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )


def _config(tmp_path: Path) -> GitSourceConfig:
    root = tmp_path / "spen-sdk"
    root.mkdir()
    return GitSourceConfig(
        clone_root=root,
        repo_name="spen-sdk",
        branch="develop",
        commit_sha="a" * 40,
        crawled_at="2026-08-05T10:00:00Z",
        budgets=GitScanBudgets(
            max_tree_entries=100,
            max_file_bytes=4096,
            max_total_raw_bytes=8192,
            max_files=20,
            max_normalized_bytes=4096,
            max_in_memory_bytes=16384,
        ),
        case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
    )


class FakeReader:
    def __init__(self, snapshot: GitRepositorySnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def read(self, *, config: GitSourceConfig) -> GitRepositorySnapshot:
        self.calls += 1
        return self.snapshot


class FakeTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(tuple(CharacterSpan(index, index + 1) for index in range(len(text))))


class ForgedTokenizer:
    def tokenize(self, *, text: str) -> object:
        return object()


class BadSpanTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        forged = object.__new__(CharacterSpan)
        object.__setattr__(forged, "start", -1)
        object.__setattr__(forged, "end", 1)
        return TokenizationResult((forged,))


class FloatSpanTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        forged = object.__new__(CharacterSpan)
        object.__setattr__(forged, "start", 0.5)
        object.__setattr__(forged, "end", 1.5)
        return TokenizationResult((forged,))


def _snapshot() -> GitRepositorySnapshot:
    observations = (
        GitFileObservation(
            path="README.md",
            raw_bytes=b"hello\nworld",
            raw_byte_size=11,
            normalized_text="hello\nworld",
            normalized_byte_size=11,
            symbol_authority=False,
        ),
        GitFileObservation(
            path="src/main.cpp",
            raw_bytes=b"int main(){}",
            raw_byte_size=12,
            normalized_text="int main(){}",
            normalized_byte_size=12,
            symbol_authority=True,
        ),
    )
    return GitRepositorySnapshot(
        repo_name="spen-sdk",
        branch="develop",
        commit_sha="a" * 40,
        observations=observations,
        metrics=GitScanMetrics(
            seen=2,
            included=2,
            excluded_generated=0,
            excluded_vendor=0,
            excluded_binary=0,
            excluded_bytes=0,
            included_raw_bytes=23,
            included_normalized_bytes=23,
            included_chunk_count=0,
        ),
    )


def test_builds_schema_valid_document_and_fallback_chunk(tmp_path: Path) -> None:
    reader = FakeReader(_snapshot())
    result = BuildGitCodeDocuments(
        repository_reader=reader,
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.status is GitCodeBuildStatus.SUCCESS
    assert result.plan is not None
    assert len(result.plan.documents) == 2
    assert len(result.plan.chunks) == 1
    assert result.plan.chunks[0]["content_kind"] == "code_window"
    assert result.plan.chunks[0]["source_version"] == "a" * 40


def test_forged_tokenizer_fails_without_partial_plan(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=ForgedTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.plan is None
    assert result.error_category is GitCodeBuildFailureCategory.TOKENIZER_FAILED


def test_non_integral_tokenizer_offsets_fail_closed(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FloatSpanTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.plan is None
    assert result.error_category is GitCodeBuildFailureCategory.TOKENIZER_FAILED


def test_plan_model_rejects_forged_document_semantics(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.plan is not None
    forged_document = dict(result.plan.documents[0])
    forged_document["content_hash"] = "0" * 64
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=(forged_document, result.plan.documents[1]),
            authority_observations=result.plan.authority_observations,
            chunks=result.plan.chunks,
            metrics=result.plan.metrics,
        )


def test_plan_model_rejects_impossible_line_range_and_metrics(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.plan is not None
    forged_chunk = dict(result.plan.chunks[0])
    forged_chunk["line_start"] = 999
    forged_chunk["line_end"] = 1000
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=(forged_chunk,),
            metrics=result.plan.metrics,
        )
    with pytest.raises(ValueError):
        GitScanMetrics(
            seen=2,
            included=2,
            excluded_generated=0,
            excluded_vendor=0,
            excluded_binary=0,
            excluded_bytes=1,
            included_raw_bytes=23,
            included_normalized_bytes=23,
            included_chunk_count=1,
        )


def test_plan_model_rejects_authority_provenance_and_zero_tokens(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.plan is not None
    alternate = GitFileObservation(
        path="src/main.cpp",
        raw_bytes=b"forged",
        raw_byte_size=6,
        normalized_text="forged",
        normalized_byte_size=6,
        symbol_authority=True,
    )
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=(alternate,),
            chunks=result.plan.chunks,
            metrics=result.plan.metrics,
        )
    forged_body = dict(result.plan.chunks[0])
    forged_body["text"] = "# spen-sdk \u00b7 README.md\n\nforged"
    forged_body["content_hash"] = ContentHasher.hash_text(forged_body["text"])
    forged_body["chunk_id"] = ChunkIdGenerator.generate_chunk_id(
        "git", "git:spen-sdk:README.md", "README.md#w0", forged_body["text"]
    )
    forged_body["token_count"] = len(forged_body["text"])
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=(forged_body,),
            metrics=result.plan.metrics,
        )
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=(
                result.plan.authority_observations[0],
                result.plan.authority_observations[0],
            ),
            chunks=result.plan.chunks,
            metrics=result.plan.metrics,
        )
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=result.plan.chunks,
            metrics=replace(result.plan.metrics, included_raw_bytes=result.plan.metrics.included_raw_bytes + 1),
        )
    forged_chunk = dict(result.plan.chunks[0])
    forged_chunk["token_count"] = 0
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=(forged_chunk,),
            metrics=result.plan.metrics,
        )


def test_snapshot_rejects_forged_unsafe_observation_path() -> None:
    forged = object.__new__(GitFileObservation)
    object.__setattr__(forged, "path", "../evil.md")
    object.__setattr__(forged, "raw_bytes", b"evil")
    object.__setattr__(forged, "raw_byte_size", 4)
    object.__setattr__(forged, "normalized_text", "evil")
    object.__setattr__(forged, "normalized_byte_size", 4)
    object.__setattr__(forged, "symbol_authority", False)
    with pytest.raises(ValueError):
        GitRepositorySnapshot(
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            observations=(forged,),
            metrics=GitScanMetrics(
                seen=1,
                included=1,
                excluded_generated=0,
                excluded_vendor=0,
                excluded_binary=0,
                excluded_bytes=0,
                included_raw_bytes=4,
                included_normalized_bytes=4,
                included_chunk_count=0,
            ),
        )


def test_plan_rejects_non_advancing_ranges_and_forged_identity(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.plan is not None
    duplicate = dict(result.plan.chunks[0])
    duplicate["part_index"] = 1
    duplicate["part_total"] = 2
    duplicate["chunk_id"] = ChunkIdGenerator.generate_chunk_id(
        "git", "git:spen-sdk:README.md", "README.md#w1", duplicate["text"]
    )
    with pytest.raises(ValueError):
        CodeDocumentPlan(
            repo_name=result.plan.repo_name,
            branch=result.plan.branch,
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=(result.plan.chunks[0], duplicate),
            metrics=replace(result.plan.metrics, included_chunk_count=2),
        )

    class EqualString:
        def __eq__(self, other: object) -> bool:
            return other in {"spen-sdk", "develop"}

    with pytest.raises(TypeError):
        CodeDocumentPlan(
            repo_name=EqualString(),  # type: ignore[arg-type]
            branch="develop",
            commit_sha=result.plan.commit_sha,
            observations=result.plan.observations,
            documents=result.plan.documents,
            authority_observations=result.plan.authority_observations,
            chunks=result.plan.chunks,
            metrics=result.plan.metrics,
        )


def test_snapshot_rejects_casefold_colliding_paths() -> None:
    first = GitFileObservation(
        path="A.py",
        raw_bytes=b"a",
        raw_byte_size=1,
        normalized_text="a",
        normalized_byte_size=1,
        symbol_authority=False,
    )
    second = GitFileObservation(
        path="a.py",
        raw_bytes=b"b",
        raw_byte_size=1,
        normalized_text="b",
        normalized_byte_size=1,
        symbol_authority=False,
    )
    with pytest.raises(ValueError):
        GitRepositorySnapshot(
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            observations=(first, second),
            metrics=GitScanMetrics(
                seen=2,
                included=2,
                excluded_generated=0,
                excluded_vendor=0,
                excluded_binary=0,
                excluded_bytes=0,
                included_raw_bytes=2,
                included_normalized_bytes=2,
                included_chunk_count=0,
            ),
        )


def test_observation_rejects_unsupported_controls() -> None:
    with pytest.raises(ValueError):
        GitFileObservation(
            path="README.md",
            raw_bytes=b"bad\x01",
            raw_byte_size=4,
            normalized_text="bad\x01",
            normalized_byte_size=4,
            symbol_authority=False,
        )


def test_execute_rejects_forged_snapshot_and_request_nested_types(tmp_path: Path) -> None:
    class AlwaysEqual:
        def __eq__(self, other: object) -> bool:
            return True

    snapshot = _snapshot()
    forged_snapshot = object.__new__(GitRepositorySnapshot)
    object.__setattr__(forged_snapshot, "repo_name", AlwaysEqual())
    object.__setattr__(forged_snapshot, "branch", AlwaysEqual())
    object.__setattr__(forged_snapshot, "commit_sha", AlwaysEqual())
    object.__setattr__(forged_snapshot, "observations", snapshot.observations)
    object.__setattr__(forged_snapshot, "metrics", snapshot.metrics)
    reader = FakeReader(forged_snapshot)
    use_case = BuildGitCodeDocuments(
        repository_reader=reader,
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    )
    config = _config(tmp_path)
    result = use_case.execute(BuildGitCodeDocumentsRequest(config, _profile()))
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.error_category is GitCodeBuildFailureCategory.RESULT_INVALID

    class Proxy:
        def __init__(self, value: object) -> None:
            self._value = value

        def __getattr__(self, name: str) -> object:
            return getattr(self._value, name)

    forged_request = object.__new__(BuildGitCodeDocumentsRequest)
    object.__setattr__(forged_request, "config", config)
    object.__setattr__(forged_request, "chunking_profile", Proxy(_profile()))
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(forged_request)
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.error_category is GitCodeBuildFailureCategory.INVALID_REQUEST


def test_wrong_request_type_fails_before_reader_call(tmp_path: Path) -> None:
    reader = FakeReader(_snapshot())
    result = BuildGitCodeDocuments(
        repository_reader=reader,
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(object())  # type: ignore[arg-type]
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.error_category is GitCodeBuildFailureCategory.INVALID_REQUEST
    assert reader.calls == 0


def test_forged_snapshot_content_fails_closed(tmp_path: Path) -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError):
        GitFileObservation(
            path="README.md",
            raw_bytes=b"different",
            raw_byte_size=9,
            normalized_text="hello\nworld",
            normalized_byte_size=11,
            symbol_authority=False,
        )
    forged = object.__new__(GitFileObservation)
    object.__setattr__(forged, "path", "README.md")
    object.__setattr__(forged, "raw_bytes", b"different")
    object.__setattr__(forged, "raw_byte_size", 9)
    object.__setattr__(forged, "normalized_text", "hello\nworld")
    object.__setattr__(forged, "normalized_byte_size", 11)
    object.__setattr__(forged, "symbol_authority", False)
    with pytest.raises(ValueError):
        GitRepositorySnapshot(
            repo_name="spen-sdk",
            branch="develop",
            commit_sha="a" * 40,
            observations=(forged, snapshot.observations[1]),
            metrics=GitScanMetrics(
                seen=2,
                included=2,
                excluded_generated=0,
                excluded_vendor=0,
                excluded_binary=0,
                excluded_bytes=0,
                included_raw_bytes=21,
                included_normalized_bytes=23,
                included_chunk_count=0,
            ),
        )


def test_negative_tokenizer_span_fails_closed(tmp_path: Path) -> None:
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=BadSpanTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(_config(tmp_path), _profile()))
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.error_category is GitCodeBuildFailureCategory.TOKENIZER_FAILED


def test_memory_budget_is_enforced(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tiny = replace(
        config,
        budgets=GitScanBudgets(
            max_tree_entries=100,
            max_file_bytes=4096,
            max_total_raw_bytes=8192,
            max_files=20,
            max_normalized_bytes=64,
            max_in_memory_bytes=64,
        ),
    )
    result = BuildGitCodeDocuments(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(tiny, _profile()))
    assert result.status is GitCodeBuildStatus.FAILED
    assert result.error_category is GitCodeBuildFailureCategory.BUDGET_EXCEEDED


def test_constructor_rejects_malformed_dependencies() -> None:
    with pytest.raises(TypeError):
        BuildGitCodeDocuments(  # type: ignore[arg-type]
            repository_reader=None,
            tokenizer=FakeTokenizer(),
            schema_validator=FoundationSchemaValidator(),
        )
