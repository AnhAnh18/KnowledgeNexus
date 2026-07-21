from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class ConfluencePageSource:
    """Trusted source fields extracted from one preserved Confluence page."""

    page_id: str
    title: str
    space_key: str
    source_version: str
    updated_at: str
    storage_xhtml: str


@dataclass(frozen=True, repr=False)
class ConfluenceStorageNormalization:
    """Deterministic storage-format normalization output."""

    normalized_body_text: str
    counters: dict[str, object]
    warnings: tuple[dict[str, object], ...]


@dataclass(frozen=True, repr=False)
class ConfluencePageNormalizationResult:
    """One normalized page and its schema-shaped canonical document."""

    normalized_body_text: str
    canonical_document: dict[str, object]
    counters: dict[str, object]
    warnings: tuple[dict[str, object], ...]
