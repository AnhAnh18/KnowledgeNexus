from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConfluenceChunkingFailureCategory(StrEnum):
    """Sanitized M6D-D failure categories safe for operator output."""

    CANONICAL_DOCUMENT_VALIDATION_FAILED = "canonical_document_validation_failed"
    DOCUMENT_STRUCTURE_IDENTITY_MISMATCH = "document_structure_identity_mismatch"
    BREADCRUMB_OVER_HARD_MAX = "breadcrumb_over_hard_max"
    UNSPLITTABLE_PROSE_FRAGMENT = "unsplittable_prose_fragment"
    UNSPLITTABLE_CODE_LINE = "unsplittable_code_line"
    UNSPLITTABLE_TABLE_HEADER = "unsplittable_table_header"
    UNSPLITTABLE_TABLE_ROW = "unsplittable_table_row"
    CHUNK_BUDGET_VIOLATION = "chunk_budget_violation"
    CHUNK_ID_COLLISION = "chunk_id_collision"
    CHUNK_RECORD_VALIDATION_FAILED = "chunk_record_validation_failed"
    CHUNKING_FAILED = "chunking_failed"


class ConfluenceChunkingError(Exception):
    """A chunking failure whose message contains only a stable category."""

    def __init__(self, category: ConfluenceChunkingFailureCategory) -> None:
        if not isinstance(category, ConfluenceChunkingFailureCategory):
            raise TypeError("category expects ConfluenceChunkingFailureCategory")
        self.category = category
        super().__init__(category.value)


@dataclass(frozen=True, repr=False)
class ChunkingResult:
    """Ordered schema-shaped records and deterministic aggregate metrics."""

    records: tuple[dict[str, object], ...]
    metrics: dict[str, object]

    def __post_init__(self) -> None:
        if isinstance(self.records, (str, bytes)):
            raise TypeError("ChunkingResult.records expects a collection")
        records = tuple(self.records)
        if not all(isinstance(record, dict) for record in records):
            raise TypeError("ChunkingResult.records expects dict entries")
        if not isinstance(self.metrics, dict):
            raise TypeError("ChunkingResult.metrics expects dict")
        object.__setattr__(
            self,
            "records",
            tuple(dict(record) for record in records),
        )
        object.__setattr__(self, "metrics", _copy_json_object(self.metrics))


def _copy_json_object(value: dict[str, object]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, entry in value.items():
        if not isinstance(key, str):
            raise TypeError("ChunkingResult.metrics keys must be strings")
        if isinstance(entry, dict):
            copied[key] = _copy_json_object(entry)
        elif isinstance(entry, list):
            copied[key] = list(entry)
        elif isinstance(entry, tuple):
            copied[key] = list(entry)
        elif entry is None or isinstance(entry, (str, int, float, bool)):
            copied[key] = entry
        else:
            raise TypeError("ChunkingResult.metrics must be JSON-compatible")
    return copied
