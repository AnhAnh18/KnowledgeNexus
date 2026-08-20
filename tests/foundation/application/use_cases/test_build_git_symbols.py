from pathlib import Path

from knowledgenexus.foundation.application.use_cases.build_git_code_documents import (
    BuildGitCodeDocuments,
    BuildGitCodeDocumentsRequest,
)
from knowledgenexus.foundation.application.use_cases.build_git_symbols import BuildGitSymbols
from knowledgenexus.foundation.domain.models import (
    BuildGitSymbolsRequest,
    CharacterSpan,
    ChunkingProfile,
    GitCasePolicy,
    GitFileObservation,
    GitRepositorySnapshot,
    GitScanBudgets,
    GitScanMetrics,
    GitSourceConfig,
    GitSymbolIndexStatus,
    TokenizationResult,
    TokenizerAsset,
)
from knowledgenexus.foundation.infrastructure.parsers import TreeSitterSymbolParser
from knowledgenexus.foundation.domain.models.symbol_index import ParsedSymbol, SymbolParseResult, SymbolParseStatus
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


def _profile() -> ChunkingProfile:
    revision = "5617a9f61b028005a4858fdac845db406aefb181"
    repository = "https://huggingface.co/BAAI/bge-m3"
    return ChunkingProfile(
        chunker_version="1.3.0", profile_status="provisional_until_benchmark", active_profile="medium",
        model_name="BAAI/bge-m3", tokenizer_name="BAAI/bge-m3", tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024, maximum_model_tokens=8192, target_tokens=450, minimum_tokens=96,
        hard_maximum_tokens=1000, overlap_tokens=64, code_window_target_tokens=450,
        code_window_max_lines=40, code_window_overlap_lines=4, tokenizer_repository=repository,
        tokenizer_revision=revision, observed_license="MIT", provenance_url=f"{repository}/tree/{revision}",
        tokenizer_assets=(TokenizerAsset(filename="tokenizer.json", byte_size=1, sha256="0" * 64),),
        transformers_version="4.57.6", tokenizers_version="0.22.2", sentencepiece_version="0.2.2",
    )


class _Tokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(tuple(CharacterSpan(index, index + 1) for index in range(len(text))))


class _Reader:
    def __init__(self, snapshot: GitRepositorySnapshot) -> None:
        self.snapshot = snapshot

    def read(self, *, config: GitSourceConfig) -> GitRepositorySnapshot:
        return self.snapshot


def _plan(tmp_path: Path, source: str) -> object:
    source = TextNormalizationRules.normalize_text(source)
    root = tmp_path / "spen-sdk"
    root.mkdir()
    observation = GitFileObservation(
        path="src/a.cpp", raw_bytes=source.encode(), raw_byte_size=len(source.encode()),
        normalized_text=source, normalized_byte_size=len(source.encode()), symbol_authority=True,
    )
    snapshot = GitRepositorySnapshot(
        repo_name="spen-sdk", branch="develop", commit_sha="a" * 40,
        observations=(observation,),
        metrics=GitScanMetrics(
            seen=1, included=1, excluded_generated=0, excluded_vendor=0, excluded_binary=0,
            excluded_bytes=0, included_raw_bytes=len(source.encode()), included_normalized_bytes=len(source.encode()),
            included_chunk_count=0,
        ),
    )
    config = GitSourceConfig(
        clone_root=root, repo_name="spen-sdk", branch="develop", commit_sha="a" * 40,
        crawled_at="2026-08-05T10:00:00Z",
        budgets=GitScanBudgets(max_tree_entries=10, max_file_bytes=4096, max_total_raw_bytes=8192,
            max_files=5, max_normalized_bytes=4096, max_in_memory_bytes=16384),
        case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
    )
    return BuildGitCodeDocuments(
        repository_reader=_Reader(snapshot), tokenizer=_Tokenizer(), schema_validator=FoundationSchemaValidator(),
    ).execute(BuildGitCodeDocumentsRequest(config, _profile())).plan


def test_builds_schema_valid_symbol_records_and_chunks(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "namespace n { class A { public: void f() {} }; }\n")
    result = BuildGitSymbols(parser=TreeSitterSymbolParser(), tokenizer=_Tokenizer()).execute(
        BuildGitSymbolsRequest(plan=plan, chunking_profile=_profile(), scanned_at="2026-08-05T11:00:00Z")
    )
    assert result.status is GitSymbolIndexStatus.SUCCESS
    assert {record["symbol_type"] for record in result.symbol_records} == {"namespace", "class", "method"}
    assert all(chunk["content_kind"] == "code_symbol" for chunk in result.chunks)


def test_invalid_request_fails_before_parser_call(tmp_path: Path) -> None:
    class _Parser:
        calls = 0
        def parse(self, **kwargs: object) -> object:
            self.calls += 1
            return object()
    parser = _Parser()
    result = BuildGitSymbols(parser=parser, tokenizer=_Tokenizer()).execute(object())
    assert result.status is GitSymbolIndexStatus.FAILED
    assert parser.calls == 0


def test_forged_parser_span_fails_closed_without_output(tmp_path: Path) -> None:
    class _ForgedParser:
        def parse(self, *, path: str, language: str, source_text: str) -> SymbolParseResult:
            return SymbolParseResult(
                path=path,
                language=language,
                status=SymbolParseStatus.OK,
                symbols=(ParsedSymbol(
                    path=path, language=language, symbol_type="function", name="f", qualified_name="f",
                    signature="void f()", line_start=999, line_end=999, parent_qualified_name=None,
                    leading_comment="", parse_status=SymbolParseStatus.OK, start_byte=0, end_byte=8,
                ),),
            )
    plan = _plan(tmp_path, "void f() {}")
    result = BuildGitSymbols(parser=_ForgedParser(), tokenizer=_Tokenizer()).execute(
        BuildGitSymbolsRequest(plan=plan, chunking_profile=_profile(), scanned_at="2026-08-05T11:00:00Z")
    )
    assert result.status is GitSymbolIndexStatus.FAILED
    assert not result.symbol_records and not result.chunks
