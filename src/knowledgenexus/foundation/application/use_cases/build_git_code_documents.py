"""Build schema-valid Git documents and bounded fallback code windows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.git_code_source import (
    CodeDocumentPlan,
    GitCodeBuildError,
    GitCodeBuildFailureCategory,
    GitCodeBuildResult,
    GitCodeBuildStatus,
    GitFileObservation,
    GitRepositorySnapshot,
    GitScanMetrics,
    GitSourceConfig,
)
from knowledgenexus.foundation.domain.records.canonical_document_record_builder import (
    CanonicalDocumentRecordBuilder,
)
from knowledgenexus.foundation.domain.records.chunk_record_builder import ChunkRecordBuilder
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules
from knowledgenexus.foundation.domain.models.tokenization import CharacterSpan, TokenizationResult
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_LANGUAGE_BY_EXTENSION = {
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".inl": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".php": "php",
    ".py": "python",
    ".pyw": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".mk": "make",
    ".make": "make",
    ".gradle": "gradle",
    ".sql": "sql",
    ".xml": "xml",
    ".xsd": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    ".svg": "xml",
}
_AUTHORITY_EXTENSIONS = frozenset(
    {".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inl", ".java"}
)
_XML_EXTENSIONS = frozenset({".xml", ".xsd", ".xsl", ".xslt", ".svg"})
_SQL_EXTENSIONS = frozenset({".sql"})


@dataclass(frozen=True)
class BuildGitCodeDocumentsRequest:
    config: GitSourceConfig
    chunking_profile: ChunkingProfile

    def __post_init__(self) -> None:
        if type(self.config) is not GitSourceConfig:
            raise TypeError("config is invalid")
        if type(self.chunking_profile) is not ChunkingProfile:
            raise TypeError("chunking_profile is invalid")
        GitSourceConfig.__post_init__(self.config)
        ChunkingProfile.__post_init__(self.chunking_profile)


class BuildGitCodeDocuments:
    def __init__(
        self,
        *,
        repository_reader: object,
        tokenizer: TokenizerPort,
        schema_validator: FoundationSchemaValidator,
        document_builder: object = CanonicalDocumentRecordBuilder,
        chunk_builder: object = ChunkRecordBuilder,
        chunk_id_generator: object = ChunkIdGenerator,
    ) -> None:
        if not callable(getattr(repository_reader, "read", None)):
            raise TypeError("repository_reader is invalid")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        if not callable(getattr(document_builder, "build", None)):
            raise TypeError("document_builder is invalid")
        if not callable(getattr(chunk_builder, "build", None)):
            raise TypeError("chunk_builder is invalid")
        if not callable(getattr(chunk_id_generator, "generate_chunk_id", None)):
            raise TypeError("chunk_id_generator is invalid")
        self._repository_reader = repository_reader
        self._tokenizer = tokenizer
        self._schema_validator = schema_validator
        self._document_builder = document_builder
        self._chunk_builder = chunk_builder
        self._chunk_id_generator = chunk_id_generator

    def execute(self, request: BuildGitCodeDocumentsRequest) -> GitCodeBuildResult:
        try:
            self._validate_dependencies(request)
            snapshot = self._repository_reader.read(config=request.config)
            if type(snapshot) is not GitRepositorySnapshot:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            try:
                GitRepositorySnapshot.__post_init__(snapshot)
            except Exception as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID) from exc
            if (
                type(snapshot.repo_name) is not str
                or type(snapshot.branch) is not str
                or type(snapshot.commit_sha) is not str
                or snapshot.repo_name != request.config.repo_name
                or snapshot.branch != request.config.branch
                or snapshot.commit_sha != request.config.commit_sha
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_IDENTITY_MISMATCH)
            self._validate_snapshot(snapshot, request.config)

            documents: list[dict[str, object]] = []
            chunks: list[dict[str, object]] = []
            authority_observations: list[GitFileObservation] = []
            for observation in snapshot.observations:
                document = self._build_document(observation, request)
                documents.append(document)
                if observation.symbol_authority:
                    authority_observations.append(observation)
                    continue
                chunks.extend(self._build_windows(observation, document, request))

            metrics = GitScanMetrics(
                seen=snapshot.metrics.seen,
                included=snapshot.metrics.included,
                excluded_generated=snapshot.metrics.excluded_generated,
                excluded_vendor=snapshot.metrics.excluded_vendor,
                excluded_binary=snapshot.metrics.excluded_binary,
                excluded_bytes=snapshot.metrics.excluded_bytes,
                included_raw_bytes=snapshot.metrics.included_raw_bytes,
                included_normalized_bytes=snapshot.metrics.included_normalized_bytes,
                included_chunk_count=len(chunks),
            )
            plan = CodeDocumentPlan(
                repo_name=request.config.repo_name,
                branch=request.config.branch,
                commit_sha=request.config.commit_sha,
                observations=snapshot.observations,
                documents=tuple(documents),
                authority_observations=tuple(authority_observations),
                chunks=tuple(chunks),
                metrics=metrics,
            )
            if self._owned_bytes(plan.documents, plan.chunks, snapshot) > request.config.budgets.max_in_memory_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
            self._validate_plan(plan, request)
            return GitCodeBuildResult(status=GitCodeBuildStatus.SUCCESS, plan=plan)
        except GitCodeBuildError as exc:
            return GitCodeBuildResult(
                status=GitCodeBuildStatus.FAILED,
                error_category=exc.category,
            )
        except Exception:
            return GitCodeBuildResult(
                status=GitCodeBuildStatus.FAILED,
                error_category=GitCodeBuildFailureCategory.INTERNAL_FAILURE,
            )

    def _validate_dependencies(self, request: object) -> None:
        if type(request) is not BuildGitCodeDocumentsRequest:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        try:
            config = request.config
            profile = request.chunking_profile
        except AttributeError as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST) from exc
        if type(config) is not GitSourceConfig or type(profile) is not ChunkingProfile:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        try:
            GitSourceConfig.__post_init__(config)
            ChunkingProfile.__post_init__(profile)
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST) from exc
        if not callable(getattr(self._repository_reader, "read", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._tokenizer, "tokenize", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._schema_validator, "validate_record", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._document_builder, "build", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._chunk_builder, "build", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._chunk_id_generator, "generate_chunk_id", None)):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        profile = request.chunking_profile
        if (
            profile.chunker_version != "1.3.0"
            or profile.active_profile != "medium"
            or profile.model_name != "BAAI/bge-m3"
            or profile.tokenizer_name != "BAAI/bge-m3"
            or profile.target_tokens != 450
            or profile.minimum_tokens != 96
            or profile.hard_maximum_tokens != 1000
            or profile.overlap_tokens != 64
            or profile.code_window_target_tokens != 450
            or profile.code_window_max_lines != 40
            or profile.code_window_overlap_lines != 4
        ):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)

    def _build_document(
        self, observation: GitFileObservation, request: BuildGitCodeDocumentsRequest
    ) -> dict[str, object]:
        language = _language_for_path(observation.path)
        document_id = f"git:spen-sdk:{observation.path}"
        metadata = {
            "language": language,
            "raw_byte_size": observation.raw_byte_size,
            "normalized_byte_size": observation.normalized_byte_size,
            "symbol_authority": observation.symbol_authority,
        }
        try:
            record = self._document_builder.build(
                document_id=document_id,
                source_system="git",
                source_type="code_file",
                normalized_body_text=observation.normalized_text,
                acl_id="acl:repo:spen-sdk",
                crawled_at=request.config.crawled_at,
                title=None,
                space_key=None,
                page_id=None,
                repo="spen-sdk",
                branch="develop",
                file_path=observation.path,
                url=None,
                author=None,
                source_version=request.config.commit_sha,
                jira_keys=[],
                relation_ids=[],
                created_at=None,
                updated_at=None,
                metadata=metadata,
            )
            self._schema_validator.validate_record("CanonicalDocument", record)
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED) from exc
        if type(record) is not dict:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
        expected_keys = {
            "schema_version",
            "document_id",
            "source_system",
            "source_type",
            "title",
            "space_key",
            "page_id",
            "repo",
            "branch",
            "file_path",
            "url",
            "author",
            "source_version",
            "content_hash",
            "acl_id",
            "jira_keys",
            "relation_ids",
            "created_at",
            "updated_at",
            "crawled_at",
            "metadata",
        }
        if set(record) != expected_keys:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
        if record.get("content_hash") != ContentHasher.hash_text(observation.normalized_text):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
        if record.get("document_id") != document_id or record.get("file_path") != observation.path:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
        if record.get("metadata") != metadata:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
        return dict(record)

    def _validate_snapshot(self, snapshot: GitRepositorySnapshot, config: GitSourceConfig) -> None:
        try:
            GitScanMetrics.__post_init__(snapshot.metrics)
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID) from exc
        if snapshot.metrics.seen > config.budgets.max_tree_entries:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        if snapshot.metrics.included > config.budgets.max_files:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        raw_total = 0
        normalized_total = 0
        previous_path: str | None = None
        for observation in snapshot.observations:
            try:
                GitFileObservation.__post_init__(observation)
            except Exception as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID) from exc
            if previous_path is not None and observation.path <= previous_path:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            previous_path = observation.path
            if b"\x00" in observation.raw_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            try:
                decoded = observation.raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_UTF8) from exc
            if any(
                (ord(char) < 0x20 and char not in "\t\r\n")
                or 0x7F <= ord(char) <= 0x9F
                for char in decoded
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.UNSUPPORTED_TEXT_CONTROL)
            normalized = TextNormalizationRules.normalize_text(decoded)
            if normalized != observation.normalized_text:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if observation.raw_byte_size != len(observation.raw_bytes):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if observation.normalized_byte_size != len(normalized.encode("utf-8")):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if observation.raw_byte_size > config.budgets.max_file_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
            if observation.normalized_byte_size > config.budgets.max_normalized_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
            raw_total += observation.raw_byte_size
            normalized_total += observation.normalized_byte_size
            if observation.symbol_authority != _is_symbol_authority(observation.path):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        if raw_total + snapshot.metrics.excluded_bytes > config.budgets.max_total_raw_bytes:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        if snapshot.metrics.included_raw_bytes != raw_total or snapshot.metrics.included_normalized_bytes != normalized_total:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        if snapshot.metrics.included != len(snapshot.observations) or snapshot.metrics.included_chunk_count != 0:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        if raw_total + normalized_total > config.budgets.max_in_memory_bytes:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)

    @staticmethod
    def _owned_bytes(
        documents: tuple[dict[str, object], ...],
        chunks: tuple[dict[str, object], ...],
        snapshot: GitRepositorySnapshot,
    ) -> int:
        total = sum(
            observation.raw_byte_size + observation.normalized_byte_size
            for observation in snapshot.observations
        )
        for record in (*documents, *chunks):
            total += len(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        total += sum(len(chunk["text"].encode("utf-8")) for chunk in chunks if type(chunk.get("text")) is str)
        return total

    def _build_windows(
        self,
        observation: GitFileObservation,
        document: Mapping[str, object],
        request: BuildGitCodeDocumentsRequest,
    ) -> list[dict[str, object]]:
        if observation.normalized_text == "":
            return []
        lines = observation.normalized_text.split("\n")
        windows: list[tuple[str, int, int]] = []
        cursor = 0
        profile = request.chunking_profile
        while cursor < len(lines):
            overlap_count = 0
            if windows:
                maximum_overlap = min(profile.code_window_overlap_lines, cursor)
                for candidate in range(maximum_overlap, -1, -1):
                    start = cursor - candidate
                    trial = lines[start:cursor] + [lines[cursor]]
                    if len(trial) > profile.code_window_max_lines:
                        continue
                    if self._count_assembled(observation.path, trial) <= profile.hard_maximum_tokens:
                        overlap_count = candidate
                        break
            overlap_start = cursor - overlap_count
            first = lines[overlap_start:cursor] + [lines[cursor]]
            first_count = self._count_assembled(observation.path, first)
            if first_count > profile.hard_maximum_tokens:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.UNSPLITTABLE_CODE_LINE)
            best_end = cursor + 1
            for end in range(cursor + 2, min(len(lines), cursor + profile.code_window_max_lines - overlap_count) + 1):
                candidate_lines = lines[overlap_start:cursor] + lines[cursor:end]
                count = self._count_assembled(observation.path, candidate_lines)
                if count <= profile.target_tokens:
                    best_end = end
                    continue
                if (
                    cursor == 0
                    and first_count < profile.minimum_tokens
                    and end == cursor + 2
                    and count <= profile.hard_maximum_tokens
                ):
                    best_end = end
                break
            body_lines = lines[overlap_start:best_end]
            normalized_text = _assembled_text(observation.path, body_lines)
            token_count = self._validated_token_count(normalized_text)
            if token_count > profile.hard_maximum_tokens:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.UNSPLITTABLE_CODE_LINE)
            windows.append((normalized_text, overlap_start + 1, best_end))
            cursor = best_end

        parts: list[dict[str, object]] = []
        seen_preimages: dict[str, tuple[str, str, str, str]] = {}
        duplicate_counts: dict[str, int] = {}
        document_id = document.get("document_id")
        if type(document_id) is not str:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        stable_key = f"git:spen-sdk:{observation.path}"
        total = len(windows)
        for index, (text, line_start, line_end) in enumerate(windows):
            unit_key = f"{observation.path}#w{index}"
            preimage = ("git", stable_key, unit_key, text)
            try:
                base_id = self._chunk_id_generator.generate_chunk_id(*preimage)
            except Exception as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.CHUNK_ID_COLLISION) from exc
            if base_id in seen_preimages:
                if seen_preimages[base_id] != preimage:
                    raise GitCodeBuildError(GitCodeBuildFailureCategory.CHUNK_ID_COLLISION)
                duplicate_counts[base_id] += 1
                chunk_id = f"{base_id}-{duplicate_counts[base_id]}"
            else:
                seen_preimages[base_id] = preimage
                duplicate_counts[base_id] = 0
                chunk_id = base_id
            token_count = self._validated_token_count(text)
            try:
                record = self._chunk_builder.build(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source_system="git",
                    source_type="code_file",
                    text=text,
                    content_kind="code_window",
                    language=_language_for_path(observation.path),
                    token_count=token_count,
                    acl_tags=["repo:spen-sdk"],
                    chunker_version=request.chunking_profile.chunker_version,
                    title=None,
                    heading_path=[],
                    space_key=None,
                    page_id=None,
                    repo="spen-sdk",
                    branch="develop",
                    file_path=observation.path,
                    symbol=None,
                    line_start=line_start,
                    line_end=line_end,
                    part_index=index,
                    part_total=total,
                    jira_keys=[],
                    relation_ids=[],
                    source_version=request.config.commit_sha,
                    updated_at=None,
                )
                self._schema_validator.validate_record("ChunkRecord", record)
            except Exception as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED) from exc
            if record.get("content_hash") != ContentHasher.hash_text(text):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.SCHEMA_VALIDATION_FAILED)
            if record.get("token_count") != token_count:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
            if record.get("line_start", 0) > record.get("line_end", 0):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            parts.append(dict(record))
        return parts

    def _count_assembled(self, path: str, lines: list[str]) -> int:
        return self._validated_token_count(_assembled_text(path, lines))

    def _validated_token_count(self, text: str) -> int:
        if type(text) is not str or not text:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
        try:
            result = self._tokenizer.tokenize(text=text)
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED) from exc
        if type(result) is not TokenizationResult:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
        previous_end = 0
        try:
            spans = result.spans
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED) from exc
        if type(spans) is not tuple:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
        for span in spans:
            if type(span) is not CharacterSpan:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
            try:
                start = span.start
                end = span.end
            except Exception as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED) from exc
            if type(start) is not int or type(end) is not int:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
            if start < 0 or end <= start or start < previous_end or end > len(text):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
            previous_end = end
        if not spans:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
        return len(spans)

    def _validate_plan(self, plan: CodeDocumentPlan, request: BuildGitCodeDocumentsRequest) -> None:
        if plan.metrics.included != len(plan.documents):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        if plan.metrics.included_chunk_count != len(plan.chunks):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
        document_by_path: dict[str, dict[str, object]] = {}
        expected_document_keys = {
            "schema_version",
            "document_id",
            "source_system",
            "source_type",
            "title",
            "space_key",
            "page_id",
            "repo",
            "branch",
            "file_path",
            "url",
            "author",
            "source_version",
            "content_hash",
            "acl_id",
            "jira_keys",
            "relation_ids",
            "created_at",
            "updated_at",
            "crawled_at",
            "metadata",
        }
        for document in plan.documents:
            if (
                document.get("source_system") != "git"
                or document.get("source_type") != "code_file"
                or document.get("repo") != "spen-sdk"
                or document.get("branch") != "develop"
                or document.get("source_version") != request.config.commit_sha
                or document.get("acl_id") != "acl:repo:spen-sdk"
                or document.get("crawled_at") != request.config.crawled_at
                or set(document) != expected_document_keys
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            path = document.get("file_path")
            if type(path) is not str or path in document_by_path:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            metadata = document.get("metadata")
            if type(metadata) is not dict or set(metadata) != {
                "language",
                "raw_byte_size",
                "normalized_byte_size",
                "symbol_authority",
            }:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            document_by_path[path] = document
        document_ids = {record["document_id"] for record in plan.documents}
        chunks_by_path: dict[str, list[dict[str, object]]] = {}
        expected_chunk_keys = {
            "schema_version",
            "chunk_id",
            "document_id",
            "source_system",
            "source_type",
            "text",
            "content_kind",
            "language",
            "token_count",
            "acl_tags",
            "content_hash",
            "chunker_version",
            "jira_keys",
            "relation_ids",
            "heading_path",
            "repo",
            "branch",
            "file_path",
            "line_start",
            "line_end",
            "part_index",
            "part_total",
            "source_version",
        }
        for chunk in plan.chunks:
            if chunk.get("document_id") not in document_ids:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            path = chunk.get("file_path")
            if type(path) is not str or path not in document_by_path:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            document = document_by_path[path]
            if chunk.get("document_id") != document.get("document_id"):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if set(chunk) != expected_chunk_keys:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if (
                chunk.get("source_version") != request.config.commit_sha
                or chunk.get("content_kind") != "code_window"
                or chunk.get("language") != _language_for_path(path)
                or chunk.get("repo") != "spen-sdk"
                or chunk.get("branch") != "develop"
                or chunk.get("acl_tags") != ["repo:spen-sdk"]
                or chunk.get("chunker_version") != request.chunking_profile.chunker_version
                or chunk.get("jira_keys") != []
                or chunk.get("relation_ids") != []
                or chunk.get("heading_path") != []
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if type(chunk.get("text")) is not str or TextNormalizationRules.normalize_text(chunk["text"]) != chunk["text"]:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if chunk.get("content_hash") != ContentHasher.hash_text(chunk["text"]):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if chunk.get("token_count") != self._validated_token_count(chunk["text"]):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TOKENIZER_FAILED)
            part_index = chunk.get("part_index")
            part_total = chunk.get("part_total")
            line_start = chunk.get("line_start")
            line_end = chunk.get("line_end")
            if (
                type(part_index) is not int
                or type(part_total) is not int
                or type(line_start) is not int
                or type(line_end) is not int
                or part_index < 0
                or part_total < 1
                or part_index >= part_total
                or line_start < 1
                or line_end < line_start
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            chunks_by_path.setdefault(path, []).append(chunk)
        for path, document in document_by_path.items():
            group = sorted(chunks_by_path.get(path, []), key=lambda item: item["part_index"])
            if bool(document["metadata"]["symbol_authority"]):
                if group:
                    raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
                continue
            observation = next(
                (item for item in plan.authority_observations if item.path == path), None
            )
            if observation is not None:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            if not group:
                if document.get("content_hash") != ContentHasher.hash_text(""):
                    # Non-empty fallback documents must have at least one window.
                    metadata = document.get("metadata")
                    if type(metadata) is dict and metadata.get("normalized_byte_size") != 0:
                        raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
                continue
            metadata = document.get("metadata")
            if type(metadata) is dict and metadata.get("normalized_byte_size") == 0:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            total = len(group)
            indexes = [item["part_index"] for item in group]
            if indexes != list(range(total)) or any(item["part_total"] != total for item in group):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
            previous_end = 0
            for index, item in enumerate(group):
                if index > 0 and max(0, previous_end - item["line_start"] + 1) > 4:
                    raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
                if item["line_end"] <= previous_end:
                    raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)
                previous_end = item["line_end"]
            source_observation = next(
                (item for item in plan.observations if item.path == path), None
            )
            if source_observation is None or previous_end != max(
                1, len(source_observation.normalized_text.split("\n"))
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.RESULT_INVALID)


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return _LANGUAGE_BY_EXTENSION.get(suffix, "unknown")


def _is_symbol_authority(path: str) -> bool:
    return Path(path).suffix.casefold() in _AUTHORITY_EXTENSIONS


def _prefix_for_path(path: str) -> str:
    escaped_parts: list[str] = []
    for byte in path.encode("utf-8"):
        if byte < 128 and (chr(byte).isalnum() or chr(byte) in "._~/"):
            escaped_parts.append(chr(byte))
        else:
            escaped_parts.append(f"%{byte:02X}")
    escaped = "".join(escaped_parts)
    separator = "\u00b7"
    suffix = Path(path).suffix.casefold()
    if suffix in _XML_EXTENSIONS:
        return f"<!-- spen-sdk {separator} {escaped} -->"
    if suffix in _SQL_EXTENSIONS:
        return f"-- spen-sdk {separator} {escaped}"
    if suffix in {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".java", ".kt", ".kts", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".cs", ".php"}:
        return f"// spen-sdk {separator} {escaped}"
    return f"# spen-sdk {separator} {escaped}"


def _assembled_text(path: str, lines: list[str]) -> str:
    return TextNormalizationRules.normalize_text(f"{_prefix_for_path(path)}\n\n" + "\n".join(lines))


__all__ = ["BuildGitCodeDocuments", "BuildGitCodeDocumentsRequest"]
