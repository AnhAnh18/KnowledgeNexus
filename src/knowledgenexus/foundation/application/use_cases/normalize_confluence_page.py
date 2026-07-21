from __future__ import annotations

import re
from datetime import datetime

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageNormalizationResult,
)
from knowledgenexus.foundation.domain.records.canonical_document_record_builder import (
    CanonicalDocumentRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import AclIdGenerator, DocumentIdGenerator
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMapperPort,
    ConfluenceRawPageMappingError,
    ConfluenceStorageNormalizationError,
    ConfluenceStorageNormalizerPort,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
    RawPageReadPort,
)

CATEGORY_INVALID_PAGE_ID = "invalid_page_id"
CATEGORY_RAW_PAGE_INPUT = "raw_page_input"
CATEGORY_PAGE_PAYLOAD = "page_payload"
CATEGORY_STORAGE_XHTML = "storage_xhtml"
CATEGORY_TIMESTAMP = "timestamp"
CATEGORY_CANONICAL_DOCUMENT = "canonical_document"

_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.[0-9]+)?"
    r"(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})$"
)


class ConfluencePageNormalizationError(Exception):
    """A sanitized, category-tagged one-page normalization failure."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class NormalizeConfluencePage:
    """Normalize one preserved raw page and build one canonical document."""

    def __init__(
        self,
        *,
        raw_page_reader: RawPageReadPort,
        raw_page_mapper: ConfluenceRawPageMapperPort,
        storage_normalizer: ConfluenceStorageNormalizerPort,
    ) -> None:
        self._raw_page_reader = raw_page_reader
        self._raw_page_mapper = raw_page_mapper
        self._storage_normalizer = storage_normalizer

    def execute(
        self,
        *,
        page_id: str,
        crawled_at: str,
    ) -> ConfluencePageNormalizationResult:
        try:
            page_id = require_confluence_page_id(page_id)
        except (TypeError, ValueError) as exc:
            raise ConfluencePageNormalizationError(CATEGORY_INVALID_PAGE_ID) from exc

        if not _is_rfc3339_timestamp(crawled_at):
            raise ConfluencePageNormalizationError(CATEGORY_TIMESTAMP)

        try:
            raw_bytes = self._raw_page_reader.read_page(page_id=page_id)
        except (RawPageReadError, OSError, TypeError, ValueError) as exc:
            raise ConfluencePageNormalizationError(CATEGORY_RAW_PAGE_INPUT) from exc

        try:
            source = self._raw_page_mapper.map_page(
                raw_bytes=raw_bytes,
                expected_page_id=page_id,
            )
        except ConfluenceRawPageMappingError as exc:
            raise ConfluencePageNormalizationError(CATEGORY_PAGE_PAYLOAD) from exc

        if not _is_rfc3339_timestamp(source.updated_at):
            raise ConfluencePageNormalizationError(CATEGORY_TIMESTAMP)

        try:
            normalized = self._storage_normalizer.normalize(
                storage_xhtml=source.storage_xhtml
            )
        except ConfluenceStorageNormalizationError as exc:
            raise ConfluencePageNormalizationError(CATEGORY_STORAGE_XHTML) from exc

        document_id = DocumentIdGenerator.confluence_page_id(source.page_id)
        acl_id = AclIdGenerator.generate_acl_id(document_id)
        try:
            canonical_document = CanonicalDocumentRecordBuilder.build(
                document_id=document_id,
                source_system="confluence",
                source_type="wiki_page",
                normalized_body_text=normalized.normalized_body_text,
                acl_id=acl_id,
                crawled_at=crawled_at,
                title=source.title,
                space_key=source.space_key,
                page_id=source.page_id,
                source_version=source.source_version,
                jira_keys=[],
                relation_ids=[],
                updated_at=source.updated_at,
                metadata={},
            )
        except (TypeError, ValueError) as exc:
            raise ConfluencePageNormalizationError(
                CATEGORY_CANONICAL_DOCUMENT
            ) from exc

        return ConfluencePageNormalizationResult(
            normalized_body_text=normalized.normalized_body_text,
            canonical_document=canonical_document,
            counters=dict(normalized.counters),
            warnings=tuple(dict(warning) for warning in normalized.warnings),
        )


def _is_rfc3339_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _RFC3339.fullmatch(value)
    if match is None:
        return False
    zone = match.group("zone")
    if zone != "Z":
        hours, minutes = (int(part) for part in zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
