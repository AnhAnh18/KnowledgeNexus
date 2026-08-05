"""Validated domain values for the bounded Git symbol-index seam."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.git_code_source import CodeDocumentPlan


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_LANGUAGES = frozenset({"cpp", "java"})
_SYMBOL_TYPES = frozenset(
    {"class", "struct", "interface", "enum", "function", "method", "namespace", "package"}
)


class SymbolParseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"


class GitSymbolIndexStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class GitSymbolIndexFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_DEPENDENCY = "invalid_dependency"
    PLAN_INVALID = "plan_invalid"
    PARSER_FAILED = "parser_failed"
    PARSER_RESULT_INVALID = "parser_result_invalid"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    TOKENIZER_FAILED = "tokenizer_failed"
    UNSPLITTABLE_CODE_LINE = "unsplittable_code_line"
    CHUNK_ID_COLLISION = "chunk_id_collision"
    RESULT_INVALID = "result_invalid"
    INTERNAL_FAILURE = "internal_failure"


def _non_empty_string(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} is invalid")
    return unicodedata.normalize("NFC", value)


def _timestamp(value: object) -> str:
    if type(value) is not str or _RFC3339.fullmatch(value) is None:
        raise ValueError("scanned_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("scanned_at is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("scanned_at is invalid")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return canonical


def _json_safe(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite value")
        return value
    if type(value) is list:
        return [_json_safe(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _json_safe(item) for key, item in value.items()}
    raise TypeError("value is not JSON-safe")


@dataclass(frozen=True, repr=False)
class ParsedSymbol:
    path: str
    language: str
    symbol_type: str
    name: str
    qualified_name: str
    signature: str | None
    line_start: int
    line_end: int
    parent_qualified_name: str | None
    leading_comment: str
    parse_status: SymbolParseStatus
    start_byte: int
    end_byte: int
    body_start_byte: int | None = None
    aggregate: bool = False

    def __post_init__(self) -> None:
        for name in ("path", "language", "symbol_type", "name", "qualified_name"):
            _non_empty_string(name, getattr(self, name))
        if self.language not in _LANGUAGES:
            raise ValueError("language is invalid")
        if self.symbol_type not in _SYMBOL_TYPES:
            raise ValueError("symbol_type is invalid")
        if self.signature is not None and type(self.signature) is not str:
            raise TypeError("signature is invalid")
        if self.parent_qualified_name is not None and type(self.parent_qualified_name) is not str:
            raise TypeError("parent_qualified_name is invalid")
        if type(self.leading_comment) is not str:
            raise TypeError("leading_comment is invalid")
        if type(self.parse_status) is not SymbolParseStatus:
            raise TypeError("parse_status is invalid")
        for name in ("line_start", "line_end", "start_byte", "end_byte"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} is invalid")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError("line range is invalid")
        if self.end_byte <= self.start_byte:
            raise ValueError("byte range is invalid")
        if self.body_start_byte is not None and (
            type(self.body_start_byte) is not int
            or self.body_start_byte < self.start_byte
            or self.body_start_byte > self.end_byte
        ):
            raise ValueError("body_start_byte is invalid")
        if type(self.aggregate) is not bool:
            raise TypeError("aggregate is invalid")


@dataclass(frozen=True, repr=False)
class SymbolParseResult:
    path: str
    language: str
    status: SymbolParseStatus
    symbols: tuple[ParsedSymbol, ...]
    error_count: int = 0

    def __post_init__(self) -> None:
        _non_empty_string("path", self.path)
        if self.language not in _LANGUAGES:
            raise ValueError("language is invalid")
        if type(self.status) is not SymbolParseStatus:
            raise TypeError("status is invalid")
        if type(self.symbols) is not tuple or any(type(item) is not ParsedSymbol for item in self.symbols):
            raise TypeError("symbols are invalid")
        if type(self.error_count) is not int or self.error_count < 0:
            raise ValueError("error_count is invalid")
        previous = (-1, -1, "")
        for symbol in self.symbols:
            ParsedSymbol.__post_init__(symbol)
            if symbol.path != self.path or symbol.language != self.language:
                raise ValueError("symbol provenance is invalid")
            if symbol.parse_status is not self.status:
                raise ValueError("symbol parse status is inconsistent")
            key = (symbol.start_byte, symbol.end_byte, symbol.qualified_name)
            if key < previous:
                raise ValueError("symbols are not deterministically ordered")
            previous = key
        if self.status is SymbolParseStatus.OK and self.error_count != 0:
            raise ValueError("ok result cannot have parser errors")
        if self.status is SymbolParseStatus.PARTIAL and self.error_count < 1:
            raise ValueError("partial result requires parser errors")


@dataclass(frozen=True)
class GitSymbolIndexMetrics:
    authority_file_count: int
    symbol_count: int
    chunk_count: int
    partial_file_count: int
    fallback_file_count: int
    oversized_part_count: int

    def __post_init__(self) -> None:
        values = (
            self.authority_file_count,
            self.symbol_count,
            self.chunk_count,
            self.partial_file_count,
            self.fallback_file_count,
            self.oversized_part_count,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("metrics are invalid")
        if self.partial_file_count > self.authority_file_count:
            raise ValueError("partial count is inconsistent")
        if self.fallback_file_count > self.authority_file_count:
            raise ValueError("fallback count is inconsistent")
        if self.symbol_count > 0 and self.chunk_count < self.symbol_count:
            raise ValueError("symbol/chunk counts are inconsistent")


@dataclass(frozen=True, repr=False)
class GitSymbolIndexResult:
    status: GitSymbolIndexStatus
    symbol_records: tuple[dict[str, object], ...] = ()
    chunks: tuple[dict[str, object], ...] = ()
    metrics: GitSymbolIndexMetrics | None = None
    error_category: GitSymbolIndexFailureCategory | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not GitSymbolIndexStatus:
            raise TypeError("status is invalid")
        if type(self.symbol_records) is not tuple or type(self.chunks) is not tuple:
            raise TypeError("records/chunks are invalid")
        if any(type(record) is not dict for record in self.symbol_records) or any(
            type(chunk) is not dict for chunk in self.chunks
        ):
            raise TypeError("records/chunks entries are invalid")
        copied_records = tuple(copy.deepcopy(_json_safe(record)) for record in self.symbol_records)
        copied_chunks = tuple(copy.deepcopy(_json_safe(chunk)) for chunk in self.chunks)
        object.__setattr__(self, "symbol_records", copied_records)
        object.__setattr__(self, "chunks", copied_chunks)
        if self.status is GitSymbolIndexStatus.SUCCESS:
            if type(self.metrics) is not GitSymbolIndexMetrics or self.error_category is not None:
                raise ValueError("success result is inconsistent")
            if self.metrics.symbol_count != len(self.symbol_records) or self.metrics.chunk_count != len(self.chunks):
                raise ValueError("result metrics are inconsistent")
        else:
            if self.symbol_records or self.chunks or self.metrics is not None:
                raise ValueError("failed result must not contain output")
            if type(self.error_category) is not GitSymbolIndexFailureCategory:
                raise ValueError("failed result category is invalid")

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "status": self.status.value,
                "symbol_records": self.symbol_records,
                "chunks": self.chunks,
                "metrics": self.metrics.__dict__ if self.metrics else None,
                "error_category": self.error_category.value if self.error_category else None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


@dataclass(frozen=True)
class BuildGitSymbolsRequest:
    plan: CodeDocumentPlan
    chunking_profile: ChunkingProfile
    scanned_at: str

    def __post_init__(self) -> None:
        if type(self.plan) is not CodeDocumentPlan:
            raise TypeError("plan is invalid")
        CodeDocumentPlan.__post_init__(self.plan)
        if type(self.chunking_profile) is not ChunkingProfile:
            raise TypeError("chunking_profile is invalid")
        ChunkingProfile.__post_init__(self.chunking_profile)
        object.__setattr__(self, "scanned_at", _timestamp(self.scanned_at))


__all__ = [
    "BuildGitSymbolsRequest",
    "GitSymbolIndexFailureCategory",
    "GitSymbolIndexMetrics",
    "GitSymbolIndexResult",
    "GitSymbolIndexStatus",
    "ParsedSymbol",
    "SymbolParseResult",
    "SymbolParseStatus",
]
