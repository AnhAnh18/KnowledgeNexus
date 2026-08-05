"""Validated domain values for the bounded local Git source seam."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_DOCUMENT_ID = re.compile(r"^git:spen-sdk:.+$")
_CHUNK_ID = re.compile(r"^chunk:git:[0-9a-f]{16}(?:-[0-9]+)?$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TREE_ENTRIES = 100_000
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_RAW_BYTES = 128 * 1024 * 1024
_MAX_FILES = 20_000
_MAX_NORMALIZED_BYTES = 8 * 1024 * 1024
_MAX_IN_MEMORY_BYTES = 256 * 1024 * 1024
_AUTHORITY_EXTENSIONS = frozenset({".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inl", ".java"})
_XML_EXTENSIONS = frozenset({".xml", ".xsd", ".xsl", ".xslt", ".svg"})
_SQL_EXTENSIONS = frozenset({".sql"})
_SLASH_COMMENT_EXTENSIONS = frozenset(
    {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".java", ".kt", ".kts", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".cs", ".php"}
)
_LANGUAGE_BY_EXTENSION = {
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".h": "cpp", ".hh": "cpp",
    ".hpp": "cpp", ".hxx": "cpp", ".inl": "cpp", ".java": "java", ".kt": "kotlin",
    ".kts": "kotlin", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".go": "go", ".rs": "rust", ".cs": "csharp", ".php": "php",
    ".py": "python", ".pyw": "python", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".fish": "shell", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".cfg": "ini", ".conf": "ini", ".mk": "make", ".make": "make", ".gradle": "gradle",
    ".sql": "sql", ".xml": "xml", ".xsd": "xml", ".xsl": "xml", ".xslt": "xml", ".svg": "xml",
}


class GitCasePolicy(StrEnum):
    REJECT_CASEFOLD_COLLISIONS = "reject_casefold_collisions"


class GitCodeBuildStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class GitCodeBuildFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    REPOSITORY_READ_FAILED = "repository_read_failed"
    REPOSITORY_IDENTITY_MISMATCH = "repository_identity_mismatch"
    TREE_INVALID = "tree_invalid"
    UNSUPPORTED_TREE_ENTRY = "unsupported_tree_entry"
    PATH_INVALID = "path_invalid"
    PATH_COLLISION = "path_collision"
    BUDGET_EXCEEDED = "budget_exceeded"
    BLOB_READ_FAILED = "blob_read_failed"
    INVALID_UTF8 = "invalid_utf8"
    UNSUPPORTED_TEXT_CONTROL = "unsupported_text_control"
    INTERNAL_FAILURE = "internal_failure"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    TOKENIZER_FAILED = "tokenizer_failed"
    UNSPLITTABLE_CODE_LINE = "unsplittable_code_line"
    CHUNK_ID_COLLISION = "chunk_id_collision"
    RESULT_INVALID = "result_invalid"


class GitCodeBuildError(Exception):
    """Sanitized Git-code failure; the category is the only public detail."""

    def __init__(self, category: GitCodeBuildFailureCategory) -> None:
        if type(category) is not GitCodeBuildFailureCategory:
            raise TypeError("category expects GitCodeBuildFailureCategory")
        self.category = category
        super().__init__(category.value)


def _positive_int(value: object, field_name: str, upper: int) -> int:
    if type(value) is not int or value < 1 or value > upper:
        raise ValueError(f"{field_name} is invalid")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} is invalid")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or _RFC3339.fullmatch(value) is None:
        raise ValueError("crawled_at is invalid")
    zone = value[-1] if value.endswith("Z") else value[-6:]
    if zone != "Z":
        hours, minutes = (int(part) for part in zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError("crawled_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("crawled_at is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("crawled_at is invalid")
    return value


def _safe_path(path: object) -> str:
    if type(path) is not str or not path or path.startswith("/") or "\\" in path:
        raise ValueError("path is invalid")
    normalized = unicodedata.normalize("NFC", path)
    components = normalized.split("/")
    if any(
        not component
        or component in {".", ".."}
        or component.endswith((".", " "))
        or component.casefold() in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{index}" for index in range(1, 10)),
            *(f"lpt{index}" for index in range(1, 10)),
        }
        for component in components
    ):
        raise ValueError("path is invalid")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in normalized):
        raise ValueError("path is invalid")
    return normalized


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os, "isjunction", None)
    if callable(is_junction) and is_junction(path):
        return True
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _validate_clone_root(root: Path) -> None:
    if root.name != "spen-sdk" or not root.exists() or not root.is_dir():
        raise ValueError("clone_root is invalid")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError("clone_root is invalid")


def _json_safe(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite JSON value")
        return value
    if type(value) is list:
        return [_json_safe(entry) for entry in value]
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, entry in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            result[key] = _json_safe(entry)
        return result
    raise TypeError("value is not JSON-safe")


@dataclass(frozen=True)
class GitScanBudgets:
    max_tree_entries: int
    max_file_bytes: int
    max_total_raw_bytes: int
    max_files: int
    max_normalized_bytes: int
    max_in_memory_bytes: int

    def __post_init__(self) -> None:
        values = (
            ("max_tree_entries", self.max_tree_entries, _MAX_TREE_ENTRIES),
            ("max_file_bytes", self.max_file_bytes, _MAX_FILE_BYTES),
            ("max_total_raw_bytes", self.max_total_raw_bytes, _MAX_TOTAL_RAW_BYTES),
            ("max_files", self.max_files, _MAX_FILES),
            ("max_normalized_bytes", self.max_normalized_bytes, _MAX_NORMALIZED_BYTES),
            ("max_in_memory_bytes", self.max_in_memory_bytes, _MAX_IN_MEMORY_BYTES),
        )
        for name, value, upper in values:
            _positive_int(value, name, upper)
        if self.max_file_bytes > self.max_total_raw_bytes:
            raise ValueError("file budget exceeds aggregate budget")
        if self.max_normalized_bytes > self.max_in_memory_bytes:
            raise ValueError("normalized budget exceeds memory budget")
        if self.max_files > self.max_tree_entries:
            raise ValueError("file budget exceeds tree budget")


@dataclass(frozen=True)
class GitSourceConfig:
    clone_root: Path
    repo_name: str
    branch: str
    commit_sha: str
    crawled_at: str
    budgets: GitScanBudgets
    case_policy: GitCasePolicy

    def __post_init__(self) -> None:
        if not isinstance(self.clone_root, Path) or not self.clone_root.is_absolute():
            raise ValueError("clone_root is invalid")
        _validate_clone_root(self.clone_root)
        if type(self.repo_name) is not str or self.repo_name != "spen-sdk":
            raise ValueError("repo_name is invalid")
        if type(self.branch) is not str or self.branch != "develop":
            raise ValueError("branch is invalid")
        if type(self.commit_sha) is not str or _SHA1.fullmatch(self.commit_sha) is None:
            raise ValueError("commit_sha is invalid")
        _timestamp(self.crawled_at)
        if type(self.budgets) is not GitScanBudgets:
            raise TypeError("budgets is invalid")
        GitScanBudgets.__post_init__(self.budgets)
        if type(self.case_policy) is not GitCasePolicy:
            raise TypeError("case_policy is invalid")


@dataclass(frozen=True, repr=False)
class GitFileObservation:
    path: str
    raw_bytes: bytes
    raw_byte_size: int
    normalized_text: str
    normalized_byte_size: int
    symbol_authority: bool

    def __post_init__(self) -> None:
        path = _safe_path(self.path)
        if type(self.raw_bytes) is not bytes:
            raise TypeError("raw_bytes is invalid")
        if type(self.raw_byte_size) is not int or self.raw_byte_size != len(self.raw_bytes):
            raise ValueError("raw_byte_size is invalid")
        if type(self.normalized_text) is not str:
            raise TypeError("normalized_text is invalid")
        expected = len(self.normalized_text.encode("utf-8"))
        if type(self.normalized_byte_size) is not int or self.normalized_byte_size != expected:
            raise ValueError("normalized_byte_size is invalid")
        if type(self.symbol_authority) is not bool:
            raise TypeError("symbol_authority is invalid")
        try:
            decoded = self.raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("raw_bytes is not UTF-8") from exc
        if TextNormalizationRules.normalize_text(decoded) != self.normalized_text:
            raise ValueError("normalized_text does not match raw_bytes")
        if _has_unsupported_controls(decoded):
            raise ValueError("raw_bytes contains unsupported controls")
        expected_authority = Path(path).suffix.casefold() in _AUTHORITY_EXTENSIONS
        if self.symbol_authority is not expected_authority:
            raise ValueError("symbol_authority is invalid for path")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "raw_bytes", bytes(self.raw_bytes))

    def __repr__(self) -> str:
        return (
            "GitFileObservation(path={!r}, raw_byte_size={!r}, "
            "normalized_byte_size={!r}, symbol_authority={!r})"
        ).format(self.path, self.raw_byte_size, self.normalized_byte_size, self.symbol_authority)


@dataclass(frozen=True)
class GitScanMetrics:
    seen: int
    included: int
    excluded_generated: int
    excluded_vendor: int
    excluded_binary: int
    excluded_bytes: int
    included_raw_bytes: int
    included_normalized_bytes: int
    included_chunk_count: int

    def __post_init__(self) -> None:
        for name in (
            "seen",
            "included",
            "excluded_generated",
            "excluded_vendor",
            "excluded_binary",
            "excluded_bytes",
            "included_raw_bytes",
            "included_normalized_bytes",
            "included_chunk_count",
        ):
            _non_negative_int(getattr(self, name), name)
        if self.seen < self.included:
            raise ValueError("seen is inconsistent")
        if self.included != self.seen - (
            self.excluded_generated + self.excluded_vendor + self.excluded_binary
        ):
            raise ValueError("exclusion counters are inconsistent")
        if self.excluded_bytes > 0 and (
            self.excluded_generated + self.excluded_vendor + self.excluded_binary == 0
        ):
            raise ValueError("excluded bytes are inconsistent")


def _revalidate_metrics(metrics: GitScanMetrics) -> None:
    try:
        GitScanMetrics.__post_init__(metrics)
    except Exception as exc:
        raise ValueError("metrics are invalid") from exc


@dataclass(frozen=True, repr=False)
class GitRepositorySnapshot:
    repo_name: str
    branch: str
    commit_sha: str
    observations: tuple[GitFileObservation, ...]
    metrics: GitScanMetrics

    def __post_init__(self) -> None:
        if type(self.repo_name) is not str or self.repo_name != "spen-sdk":
            raise ValueError("repo_name is invalid")
        if type(self.branch) is not str or self.branch != "develop":
            raise ValueError("branch is invalid")
        if type(self.commit_sha) is not str or _SHA1.fullmatch(self.commit_sha) is None:
            raise ValueError("commit_sha is invalid")
        if type(self.observations) is not tuple or any(
            type(item) is not GitFileObservation for item in self.observations
        ):
            raise TypeError("observations are invalid")
        for observation in self.observations:
            GitFileObservation.__post_init__(observation)
        paths = []
        for item in self.observations:
            if _safe_path(item.path) != item.path:
                raise ValueError("observation path is invalid")
            paths.append(item.path)
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("observations are not sorted and unique")
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("observations have casefold collisions")
        if type(self.metrics) is not GitScanMetrics:
            raise TypeError("metrics are invalid")
        _revalidate_metrics(self.metrics)
        if self.metrics.included != len(self.observations):
            raise ValueError("included counter is inconsistent")
        if self.metrics.included_raw_bytes != sum(item.raw_byte_size for item in self.observations):
            raise ValueError("raw byte counter is inconsistent")
        if self.metrics.included_normalized_bytes != sum(
            item.normalized_byte_size for item in self.observations
        ):
            raise ValueError("normalized byte counter is inconsistent")
        if self.metrics.included_chunk_count != 0:
            raise ValueError("snapshot chunk counter must be zero")


def _validate_record(record: object, name: str) -> dict[str, object]:
    if type(record) is not dict:
        raise TypeError(f"{name} is invalid")
    copied = _json_safe(record)
    if type(copied) is not dict:
        raise TypeError(f"{name} is invalid")
    return copied


def _language_for_path(path: str) -> str:
    return _LANGUAGE_BY_EXTENSION.get(Path(path).suffix.casefold(), "unknown")


def _has_unsupported_controls(text: str) -> bool:
    return any(
        (ord(char) < 0x20 and char not in "\t\n\r") or 0x7F <= ord(char) <= 0x9F
        for char in text
    )


def _assembled_text(path: str, lines: list[str]) -> str:
    escaped = "".join(
        chr(byte) if byte < 128 and (chr(byte).isalnum() or chr(byte) in "._~/") else f"%{byte:02X}"
        for byte in path.encode("utf-8")
    )
    suffix = Path(path).suffix.casefold()
    if suffix in _XML_EXTENSIONS:
        prefix = f"<!-- spen-sdk \u00b7 {escaped} -->"
    elif suffix in _SQL_EXTENSIONS:
        prefix = f"-- spen-sdk \u00b7 {escaped}"
    elif suffix in _SLASH_COMMENT_EXTENSIONS:
        prefix = f"// spen-sdk \u00b7 {escaped}"
    else:
        prefix = f"# spen-sdk \u00b7 {escaped}"
    return TextNormalizationRules.normalize_text(prefix + "\n\n" + "\n".join(lines))


@dataclass(frozen=True, repr=False)
class CodeDocumentPlan:
    repo_name: str
    branch: str
    commit_sha: str
    observations: tuple[GitFileObservation, ...]
    documents: tuple[dict[str, object], ...]
    authority_observations: tuple[GitFileObservation, ...]
    chunks: tuple[dict[str, object], ...]
    metrics: GitScanMetrics

    def __post_init__(self) -> None:
        if type(self.repo_name) is not str or type(self.branch) is not str:
            raise TypeError("plan identity types are invalid")
        if self.repo_name != "spen-sdk" or self.branch != "develop":
            raise ValueError("plan identity is invalid")
        if type(self.commit_sha) is not str or _SHA1.fullmatch(self.commit_sha) is None:
            raise ValueError("plan commit is invalid")
        if type(self.observations) is not tuple or any(
            type(item) is not GitFileObservation for item in self.observations
        ):
            raise TypeError("plan observations are invalid")
        for observation in self.observations:
            if (
                type(observation.raw_bytes) is not bytes
                or type(observation.normalized_text) is not str
                or type(observation.symbol_authority) is not bool
            ):
                raise TypeError("plan observation fields are invalid")
            try:
                decoded = observation.raw_bytes.decode("utf-8")
            except (AttributeError, UnicodeDecodeError) as exc:
                raise ValueError("plan observation bytes are invalid") from exc
            if (
                type(observation.raw_byte_size) is not int
                or observation.raw_byte_size != len(observation.raw_bytes)
                or type(observation.normalized_byte_size) is not int
                or observation.normalized_byte_size != len(observation.normalized_text.encode("utf-8"))
                or TextNormalizationRules.normalize_text(decoded) != observation.normalized_text
                or _has_unsupported_controls(decoded)
                or observation.symbol_authority is not (
                    Path(observation.path).suffix.casefold() in _AUTHORITY_EXTENSIONS
                )
            ):
                raise ValueError("plan observation provenance is invalid")
            if _safe_path(observation.path) != observation.path:
                raise ValueError("plan observation path is invalid")
        observation_paths = [item.path for item in self.observations]
        if observation_paths != sorted(observation_paths) or len(observation_paths) != len(set(observation_paths)):
            raise ValueError("plan observations are not sorted and unique")
        if len({path.casefold() for path in observation_paths}) != len(observation_paths):
            raise ValueError("plan observations have casefold collisions")
        if type(self.documents) is not tuple or type(self.chunks) is not tuple:
            raise TypeError("plan records are invalid")
        documents = tuple(_validate_record(record, "document") for record in self.documents)
        chunks = tuple(_validate_record(record, "chunk") for record in self.chunks)
        if type(self.authority_observations) is not tuple or any(
            type(item) is not GitFileObservation for item in self.authority_observations
        ):
            raise TypeError("authority observations are invalid")
        authority_observation_paths = [item.path for item in self.authority_observations]
        if authority_observation_paths != sorted(authority_observation_paths) or len(
            authority_observation_paths
        ) != len(set(authority_observation_paths)):
            raise ValueError("authority observations are not sorted and unique")
        if type(self.metrics) is not GitScanMetrics:
            raise TypeError("plan metrics are invalid")
        _revalidate_metrics(self.metrics)
        document_ids = [record.get("document_id") for record in documents]
        document_keys = {
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
        if any(set(record) != document_keys for record in documents):
            raise ValueError("document field set is invalid")
        if any(type(value) is not str or not _DOCUMENT_ID.fullmatch(value) for value in document_ids):
            raise ValueError("document identity is invalid")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("duplicate document identity")
        observations_by_path = {item.path: item for item in self.observations}
        documents_by_path: dict[str, dict[str, object]] = {}
        for document in documents:
            path = document["file_path"]
            if type(path) is not str or path not in observations_by_path:
                raise ValueError("document path is inconsistent")
            observation = observations_by_path[path]
            expected_metadata = {
                "language": _language_for_path(path),
                "raw_byte_size": observation.raw_byte_size,
                "normalized_byte_size": observation.normalized_byte_size,
                "symbol_authority": observation.symbol_authority,
            }
            metadata = document["metadata"]
            if (
                type(metadata) is not dict
                or type(metadata.get("language")) is not str
                or type(metadata.get("raw_byte_size")) is not int
                or type(metadata.get("normalized_byte_size")) is not int
                or type(metadata.get("symbol_authority")) is not bool
            ):
                raise ValueError("document metadata types are invalid")
            if (
                document["schema_version"] != SCHEMA_VERSION
                or document["document_id"] != f"git:spen-sdk:{path}"
                or document["source_system"] != "git"
                or document["source_type"] != "code_file"
                or document["repo"] != "spen-sdk"
                or document["branch"] != "develop"
                or document["source_version"] != self.commit_sha
                or document["acl_id"] != "acl:repo:spen-sdk"
                or document["title"] is not None
                or document["space_key"] is not None
                or document["page_id"] is not None
                or document["url"] is not None
                or document["author"] is not None
                or document["created_at"] is not None
                or document["updated_at"] is not None
                or document["jira_keys"] != []
                or document["relation_ids"] != []
                or type(document["crawled_at"]) is not str
                or _timestamp(document["crawled_at"]) != document["crawled_at"]
                or document["metadata"] != expected_metadata
                or document["content_hash"] != ContentHasher.hash_text(observation.normalized_text)
            ):
                raise ValueError("document semantics are invalid")
            documents_by_path[path] = document
        if set(documents_by_path) != set(observations_by_path):
            raise ValueError("document observations are incomplete")
        if [document["file_path"] for document in documents] != sorted(documents_by_path):
            raise ValueError("documents are not sorted")
        if self.metrics.included != len(documents):
            raise ValueError("document count is inconsistent")
        if self.metrics.included_raw_bytes != sum(item.raw_byte_size for item in self.observations):
            raise ValueError("plan raw byte counter is inconsistent")
        if self.metrics.included_normalized_bytes != sum(item.normalized_byte_size for item in self.observations):
            raise ValueError("plan normalized byte counter is inconsistent")
        chunk_ids = [record.get("chunk_id") for record in chunks]
        chunk_keys = {
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
        if any(set(record) != chunk_keys for record in chunks):
            raise ValueError("chunk field set is invalid")
        if any(type(value) is not str or _CHUNK_ID.fullmatch(value) is None for value in chunk_ids):
            raise ValueError("chunk identity is invalid")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("duplicate chunk identity")
        if self.metrics.included_chunk_count != len(chunks):
            raise ValueError("chunk count is inconsistent")
        document_id_set = set(document_ids)
        authority_paths = {item.path for item in self.authority_observations}
        if not authority_paths.issubset(observations_by_path) or any(
            not observations_by_path[path].symbol_authority for path in authority_paths
        ):
            raise ValueError("authority observations are invalid")
        flagged_authority_paths = {
            record["file_path"]
            for record in documents
            if isinstance(record.get("metadata"), dict)
            and record["metadata"].get("symbol_authority") is True
        }
        if authority_paths != flagged_authority_paths:
            raise ValueError("authority observations are inconsistent")
        observations_by_path = {item.path: item for item in self.observations}
        for item in self.authority_observations:
            try:
                GitFileObservation.__post_init__(item)
            except Exception as exc:
                raise ValueError("authority observation provenance is invalid") from exc
            canonical = observations_by_path.get(item.path)
            if canonical is None or any(
                (
                    item.path != canonical.path,
                    item.raw_bytes != canonical.raw_bytes,
                    item.raw_byte_size != canonical.raw_byte_size,
                    item.normalized_text != canonical.normalized_text,
                    item.normalized_byte_size != canonical.normalized_byte_size,
                    item.symbol_authority is not canonical.symbol_authority,
                )
            ):
                raise ValueError("authority observation provenance is inconsistent")
        chunks_by_path: dict[str, list[dict[str, object]]] = {}
        for chunk in chunks:
            if chunk.get("document_id") not in document_id_set:
                raise ValueError("chunk document identity is inconsistent")
            if chunk.get("source_system") != "git" or chunk.get("source_type") != "code_file":
                raise ValueError("chunk source identity is invalid")
            path = chunk.get("file_path")
            if type(path) is not str or path not in documents_by_path:
                raise ValueError("chunk path is inconsistent")
            document = documents_by_path[path]
            if (
                chunk.get("schema_version") != SCHEMA_VERSION
                or chunk.get("document_id") != document["document_id"]
                or chunk.get("repo") != "spen-sdk"
                or chunk.get("branch") != "develop"
                or chunk.get("source_version") != self.commit_sha
                or chunk.get("acl_tags") != ["repo:spen-sdk"]
                or chunk.get("content_kind") != "code_window"
                or chunk.get("language") != _language_for_path(path)
                or chunk.get("chunker_version") != "1.2.0"
                or chunk.get("jira_keys") != []
                or chunk.get("relation_ids") != []
                or chunk.get("heading_path") != []
            ):
                raise ValueError("chunk semantics are invalid")
            if type(chunk.get("text")) is not str or not chunk["text"]:
                raise ValueError("chunk text is invalid")
            if chunk.get("content_hash") != ContentHasher.hash_text(chunk["text"]):
                raise ValueError("chunk content hash is invalid")
            path = chunk.get("file_path")
            part_index = chunk.get("part_index")
            expected_id = ChunkIdGenerator.generate_chunk_id(
                "git",
                f"git:spen-sdk:{path}",
                f"{path}#w{part_index}",
                chunk["text"],
            )
            if chunk.get("chunk_id") != expected_id:
                raise ValueError("chunk identity preimage is invalid")
            part_total = chunk.get("part_total")
            line_start = chunk.get("line_start")
            line_end = chunk.get("line_end")
            source_line_count = max(1, len(observations_by_path[path].normalized_text.split("\n")))
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
                or line_end > source_line_count
            ):
                raise ValueError("chunk range metadata is invalid")
            token_count = chunk.get("token_count")
            if type(token_count) is not int or token_count < 1 or token_count > 1000 or token_count > len(chunk["text"]):
                raise ValueError("chunk token count is invalid")
            source_lines = observations_by_path[path].normalized_text.split("\n")
            expected_text = _assembled_text(path, source_lines[line_start - 1 : line_end])
            if chunk["text"] != expected_text:
                raise ValueError("chunk source text is inconsistent")
            chunks_by_path.setdefault(path, []).append(chunk)
        for path, document in documents_by_path.items():
            group = chunks_by_path.get(path, [])
            if document["metadata"]["symbol_authority"] is True and group:
                raise ValueError("authority document has fallback chunks")
            if document["metadata"]["symbol_authority"] is False:
                if document["metadata"]["normalized_byte_size"] == 0 and group:
                    raise ValueError("empty fallback document has chunks")
                if document["metadata"]["normalized_byte_size"] > 0 and not group:
                    raise ValueError("non-empty fallback document has no chunks")
        for path, group in chunks_by_path.items():
            ordered = sorted(group, key=lambda item: item["part_index"])
            total = len(ordered)
            if [item["part_index"] for item in ordered] != list(range(total)):
                raise ValueError("chunk parts are not contiguous")
            if any(item["part_total"] != total for item in ordered):
                raise ValueError("chunk part totals are inconsistent")
            previous_end = 0
            for index, item in enumerate(ordered):
                if index == 0 and item["line_start"] != 1:
                    raise ValueError("chunk ranges omit source prefix")
                if index > 0 and item["line_start"] > previous_end + 1:
                    raise ValueError("chunk ranges contain a source gap")
                if index > 0 and max(0, previous_end - item["line_start"] + 1) > 4:
                    raise ValueError("chunk overlap exceeds bound")
                if item["line_end"] <= previous_end:
                    raise ValueError("chunk ranges do not advance")
                previous_end = item["line_end"]
            source_line_count = max(1, len(observations_by_path[path].normalized_text.split("\n")))
            if previous_end != source_line_count:
                raise ValueError("chunk ranges omit source suffix")
        object.__setattr__(self, "documents", documents)
        object.__setattr__(self, "chunks", chunks)

    def to_bytes(self) -> bytes:
        payload = {
            "repo_name": self.repo_name,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "documents": self.documents,
            "chunks": self.chunks,
            "metrics": self.metrics.__dict__,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


@dataclass(frozen=True)
class GitCodeBuildResult:
    status: GitCodeBuildStatus
    plan: CodeDocumentPlan | None = None
    error_category: GitCodeBuildFailureCategory | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not GitCodeBuildStatus:
            raise TypeError("status is invalid")
        if self.status is GitCodeBuildStatus.SUCCESS:
            if type(self.plan) is not CodeDocumentPlan or self.error_category is not None:
                raise ValueError("success result is inconsistent")
            try:
                CodeDocumentPlan.__post_init__(self.plan)
            except Exception as exc:
                raise ValueError("success plan is invalid") from exc
        else:
            if self.plan is not None or type(self.error_category) is not GitCodeBuildFailureCategory:
                raise ValueError("failed result is inconsistent")
