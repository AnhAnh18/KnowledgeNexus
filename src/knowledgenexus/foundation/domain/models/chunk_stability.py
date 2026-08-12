from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
)
from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher


SUMMARY_FORMAT_VERSION = "1"
ACTIVE_CHUNKER_VERSION = "1.2.0"
_CHUNK_ID = re.compile(r"^chunk:(?:confluence|git):[0-9a-f]{16}(?:-[1-9][0-9]*)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENT_ID = re.compile(r"^(?:confluence:page|git):\S+$")
_CONTENT_KINDS = frozenset({"prose", "table", "code_block", "code_symbol", "code_window"})


class ChunkStabilityFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    SCHEMA_INVALID = "schema_invalid"
    PROFILE_MISMATCH = "profile_mismatch"
    DOCUMENT_INVALID = "document_invalid"
    CHUNK_INVALID = "chunk_invalid"
    CROSS_DOCUMENT_MISMATCH = "cross_document_mismatch"
    DUPLICATE_ID = "duplicate_id"
    ORDER_INVALID = "order_invalid"
    METRICS_INVALID = "metrics_invalid"


class ChunkStabilityError(Exception):
    """Sanitized M8-E failure containing only a stable category."""

    def __init__(self, category: ChunkStabilityFailureCategory) -> None:
        if type(category) is not ChunkStabilityFailureCategory:
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category.value!r})"


def _require_exact_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{field_name} is invalid")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{field_name} is invalid")
    return value


@dataclass(frozen=True, repr=False)
class ChunkStabilityEntry:
    chunk_id: str
    content_hash: str
    content_kind: str
    token_count: int
    part_index: int | None = None
    part_total: int | None = None

    def __post_init__(self) -> None:
        chunk_id = _require_exact_string(self.chunk_id, "chunk_id")
        if _CHUNK_ID.fullmatch(chunk_id) is None:
            raise ValueError("chunk_id is invalid")
        _require_sha256(self.content_hash, "content_hash")
        if type(self.content_kind) is not str or self.content_kind not in _CONTENT_KINDS:
            raise ValueError("content_kind is invalid")
        token_count = _require_non_negative_int(self.token_count, "token_count")
        if token_count > 1000:
            raise ValueError("token_count is invalid")

        if self.part_index is None or self.part_total is None:
            if self.part_index is not None or self.part_total is not None:
                raise ValueError("part metadata is incomplete")
        else:
            part_index = _require_non_negative_int(self.part_index, "part_index")
            part_total = self.part_total
            if type(part_total) is not int or part_total < 1:
                raise ValueError("part_total is invalid")
            if part_index >= part_total:
                raise ValueError("part metadata is inconsistent")

    def to_payload(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "content_kind": self.content_kind,
            "part_index": self.part_index,
            "part_total": self.part_total,
            "token_count": self.token_count,
        }


@dataclass(frozen=True, repr=False)
class DocumentChunkSetSummary:
    format_version: str
    document_id: str
    document_content_hash: str
    chunker_version: str
    profile_identity: str
    entries: tuple[ChunkStabilityEntry, ...]
    chunk_count: int
    content_kind_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if type(self.format_version) is not str or self.format_version != SUMMARY_FORMAT_VERSION:
            raise ValueError("format_version is invalid")
        if type(self.document_id) is not str or _DOCUMENT_ID.fullmatch(self.document_id) is None:
            raise ValueError("document_id is invalid")
        _require_sha256(self.document_content_hash, "document_content_hash")
        if type(self.chunker_version) is not str or self.chunker_version != ACTIVE_CHUNKER_VERSION:
            raise ValueError("chunker_version is invalid")
        if type(self.profile_identity) is not str or self.profile_identity != ACTIVE_PAGE_SET_PROFILE_IDENTITY:
            raise ValueError("profile_identity is invalid")
        if type(self.entries) is not tuple or any(
            type(entry) is not ChunkStabilityEntry for entry in self.entries
        ):
            raise TypeError("entries are invalid")
        if type(self.chunk_count) is not int or self.chunk_count < 0:
            raise TypeError("chunk_count is invalid")
        if self.chunk_count != len(self.entries):
            raise ValueError("chunk_count is inconsistent")

        seen_ids: set[str] = set()
        for entry in self.entries:
            if entry.chunk_id in seen_ids:
                raise ValueError("entries contain duplicate IDs")
            seen_ids.add(entry.chunk_id)

        if type(self.content_kind_counts) is not tuple:
            raise TypeError("content_kind_counts are invalid")
        counts: list[tuple[str, int]] = []
        previous: str | None = None
        for pair in self.content_kind_counts:
            if type(pair) is not tuple or len(pair) != 2:
                raise TypeError("content_kind_counts entries are invalid")
            kind, count = pair
            if type(kind) is not str or kind not in _CONTENT_KINDS:
                raise ValueError("content_kind_counts kind is invalid")
            if previous is not None and kind <= previous:
                raise ValueError("content_kind_counts are not sorted and unique")
            _require_non_negative_int(count, "content_kind_counts count")
            counts.append((kind, count))
            previous = kind
        if sum(count for _, count in counts) != self.chunk_count:
            raise ValueError("content_kind_counts are inconsistent")
        expected = {}
        for entry in self.entries:
            expected[entry.content_kind] = expected.get(entry.content_kind, 0) + 1
        if tuple(sorted(expected.items())) != tuple(counts):
            raise ValueError("content_kind_counts do not match entries")
        object.__setattr__(self, "content_kind_counts", tuple(counts))

    def _payload(self) -> dict[str, object]:
        return {
            "chunk_count": self.chunk_count,
            "content_kind_counts": [
                [kind, count] for kind, count in self.content_kind_counts
            ],
            "document_content_hash": self.document_content_hash,
            "document_id": self.document_id,
            "entries": [entry.to_payload() for entry in self.entries],
            "format_version": self.format_version,
            "profile_identity": self.profile_identity,
            "chunker_version": self.chunker_version,
        }

    def to_canonical_json(self) -> bytes:
        return json.dumps(
            self._payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json()).hexdigest()


__all__ = [
    "ACTIVE_CHUNKER_VERSION",
    "ChunkStabilityEntry",
    "ChunkStabilityError",
    "ChunkStabilityFailureCategory",
    "DocumentChunkSetSummary",
    "SUMMARY_FORMAT_VERSION",
]
