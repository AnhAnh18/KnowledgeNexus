from __future__ import annotations

import re
from typing import Protocol

from knowledgenexus.foundation.domain.models.chunk_stability import (
    ACTIVE_CHUNKER_VERSION,
    ChunkStabilityEntry,
    ChunkStabilityError,
    ChunkStabilityFailureCategory,
    DocumentChunkSetSummary,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetResult,
)
from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_DOCUMENT_ID = re.compile(r"^confluence:page:\S+$")
_CONTENT_KINDS = frozenset({"prose", "table", "code_block", "code_symbol", "code_window"})


class _SchemaValidatorPort(Protocol):
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None: ...


def _fail(category: ChunkStabilityFailureCategory) -> None:
    raise ChunkStabilityError(category)


class ChunkStabilitySummaryBuilder:
    """Project validated Foundation records into a text-free stability handoff."""

    @classmethod
    def build_document(
        cls,
        *,
        canonical_document: object,
        chunks: object,
        schema_validator: object | None = None,
        profile_identity: object = ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ) -> DocumentChunkSetSummary:
        if type(canonical_document) is not dict or type(chunks) is not tuple:
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        if type(profile_identity) is not str or profile_identity != ACTIVE_PAGE_SET_PROFILE_IDENTITY:
            _fail(ChunkStabilityFailureCategory.PROFILE_MISMATCH)
        validator = cls._validator(schema_validator)

        cls._validate_document(canonical_document, validator)
        document_id = canonical_document.get("document_id")
        if type(document_id) is not str or _DOCUMENT_ID.fullmatch(document_id) is None:
            _fail(ChunkStabilityFailureCategory.DOCUMENT_INVALID)
        document_hash = canonical_document.get("content_hash")
        if type(document_hash) is not str:
            _fail(ChunkStabilityFailureCategory.DOCUMENT_INVALID)

        entries: list[ChunkStabilityEntry] = []
        seen_ids: set[str] = set()
        part_total: int | None = None
        part_kind: str | None = None
        expected_part_index = 0
        for chunk in chunks:
            if type(chunk) is not dict:
                _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
            cls._validate_chunk(chunk, validator)
            chunk_document_id = chunk.get("document_id")
            if type(chunk_document_id) is not str:
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)
            if chunk_document_id != document_id:
                _fail(ChunkStabilityFailureCategory.CROSS_DOCUMENT_MISMATCH)
            chunker_version = chunk.get("chunker_version")
            if type(chunker_version) is not str:
                _fail(ChunkStabilityFailureCategory.PROFILE_MISMATCH)
            if chunker_version != ACTIVE_CHUNKER_VERSION:
                _fail(ChunkStabilityFailureCategory.PROFILE_MISMATCH)
            chunk_id = chunk.get("chunk_id")
            if type(chunk_id) is not str:
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)
            if chunk_id in seen_ids:
                _fail(ChunkStabilityFailureCategory.DUPLICATE_ID)
            seen_ids.add(chunk_id)

            text = chunk.get("text")
            content_hash = chunk.get("content_hash")
            if type(text) is not str or type(content_hash) is not str:
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)
            try:
                expected_hash = ContentHasher.hash_text(text)
            except (TypeError, ValueError):
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)
            if content_hash != expected_hash:
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)

            part_index = chunk.get("part_index")
            part_total_value = chunk.get("part_total")
            if part_index is None and part_total_value is None:
                if part_total is not None and expected_part_index != part_total:
                    _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                part_total = None
                part_kind = None
                expected_part_index = 0
            elif part_index is None or part_total_value is None:
                _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
            else:
                if type(part_index) is not int or type(part_total_value) is not int:
                    _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                if part_index < 0 or part_total_value < 1 or part_index >= part_total_value:
                    _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                if part_total is None:
                    if part_index != 0:
                        _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                    part_total = part_total_value
                    part_kind = chunk.get("content_kind") if type(chunk.get("content_kind")) is str else None
                    expected_part_index = 1
                    if part_total == 1:
                        part_total = None
                        part_kind = None
                        expected_part_index = 0
                else:
                    if (
                        part_total_value != part_total
                        or part_index != expected_part_index
                        or chunk.get("content_kind") != part_kind
                    ):
                        _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                    expected_part_index += 1
                    if expected_part_index == part_total:
                        part_total = None
                        part_kind = None
                        expected_part_index = 0

            try:
                entries.append(
                    ChunkStabilityEntry(
                        chunk_id=chunk_id,
                        content_hash=content_hash,
                        content_kind=chunk.get("content_kind"),
                        token_count=chunk.get("token_count"),
                        part_index=part_index,
                        part_total=part_total_value,
                    )
                )
            except (TypeError, ValueError):
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)

        if part_total is not None:
            _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.content_kind] = counts.get(entry.content_kind, 0) + 1
        try:
            return DocumentChunkSetSummary(
                format_version="1",
                document_id=document_id,
                document_content_hash=document_hash,
                chunker_version=ACTIVE_CHUNKER_VERSION,
                profile_identity=profile_identity,
                entries=tuple(entries),
                chunk_count=len(entries),
                content_kind_counts=tuple(sorted(counts.items())),
            )
        except (TypeError, ValueError):
            _fail(ChunkStabilityFailureCategory.METRICS_INVALID)

    @classmethod
    def build_page_set(
        cls,
        *,
        result: object,
        schema_validator: object | None = None,
    ) -> tuple[DocumentChunkSetSummary, ...]:
        if type(result) is not ConfluencePageSetResult:
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        try:
            result = ConfluencePageSetResult(
                documents=result.documents,
                chunks=result.chunks,
                page_metrics=result.page_metrics,
                metrics=result.metrics,
            )
        except Exception:
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        validator = cls._validator(schema_validator)
        for document in result.documents:
            if type(document) is not dict:
                _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
            cls._validate_document(document, validator)
        for chunk in result.chunks:
            if type(chunk) is not dict:
                _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
            cls._validate_chunk(chunk, validator)
        document_ids: list[str] = []
        for document in result.documents:
            if type(document) is not dict or type(document.get("document_id")) is not str:
                _fail(ChunkStabilityFailureCategory.DOCUMENT_INVALID)
            document_id = document["document_id"]
            if document_id in document_ids:
                _fail(ChunkStabilityFailureCategory.DUPLICATE_ID)
            document_ids.append(document_id)

        groups: dict[str, list[dict[str, object]]] = {document_id: [] for document_id in document_ids}
        seen_document_ids: set[str] = set()
        seen_chunk_ids: set[str] = set()
        document_positions = {document_id: index for index, document_id in enumerate(document_ids)}
        last_position = -1
        previous_document_id: str | None = None
        for chunk in result.chunks:
            if type(chunk) is not dict:
                _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
            document_id = chunk.get("document_id")
            if type(document_id) is not str or document_id not in groups:
                _fail(ChunkStabilityFailureCategory.CROSS_DOCUMENT_MISMATCH)
            chunk_id = chunk.get("chunk_id")
            if type(chunk_id) is not str:
                _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)
            if chunk_id in seen_chunk_ids:
                _fail(ChunkStabilityFailureCategory.DUPLICATE_ID)
            seen_chunk_ids.add(chunk_id)
            position = document_positions[document_id]
            if position < last_position:
                _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
            last_position = position
            if previous_document_id != document_id:
                if document_id in seen_document_ids:
                    _fail(ChunkStabilityFailureCategory.ORDER_INVALID)
                seen_document_ids.add(document_id)
                previous_document_id = document_id
            groups[document_id].append(chunk)

        summaries = tuple(
            cls.build_document(
                canonical_document=document,
                chunks=tuple(groups[document["document_id"]]),
                schema_validator=validator,
            )
            for document in result.documents
        )
        if len(summaries) != result.metrics.document_count:
            _fail(ChunkStabilityFailureCategory.METRICS_INVALID)
        if sum(summary.chunk_count for summary in summaries) != result.metrics.chunk_count:
            _fail(ChunkStabilityFailureCategory.METRICS_INVALID)
        aggregate: dict[str, int] = {}
        for summary in summaries:
            for kind, count in summary.content_kind_counts:
                aggregate[kind] = aggregate.get(kind, 0) + count
        if tuple(sorted(aggregate.items())) != result.metrics.content_kind_counts:
            _fail(ChunkStabilityFailureCategory.METRICS_INVALID)
        return summaries

    @staticmethod
    def _validator(schema_validator: object | None) -> _SchemaValidatorPort:
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        except Exception:
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        try:
            validate_record = getattr(validator, "validate_record", None)
        except Exception:
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        if not callable(validate_record):
            _fail(ChunkStabilityFailureCategory.INVALID_INPUT)
        return validator

    @staticmethod
    def _validate_document(document: dict[str, object], validator: _SchemaValidatorPort) -> None:
        try:
            validator.validate_record("CanonicalDocument", document)
        except Exception:
            _fail(ChunkStabilityFailureCategory.SCHEMA_INVALID)
        if (
            type(document.get("source_system")) is not str
            or document.get("source_system") != "confluence"
            or type(document.get("source_type")) is not str
            or document.get("source_type") != "wiki_page"
        ):
            _fail(ChunkStabilityFailureCategory.DOCUMENT_INVALID)
        content_hash = document.get("content_hash")
        if type(content_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            _fail(ChunkStabilityFailureCategory.DOCUMENT_INVALID)

    @staticmethod
    def _validate_chunk(chunk: dict[str, object], validator: _SchemaValidatorPort) -> None:
        try:
            validator.validate_record("ChunkRecord", chunk)
        except Exception:
            _fail(ChunkStabilityFailureCategory.SCHEMA_INVALID)
        if (
            type(chunk.get("source_system")) is not str
            or chunk.get("source_system") != "confluence"
            or type(chunk.get("source_type")) is not str
            or chunk.get("source_type") != "wiki_page"
        ):
            _fail(ChunkStabilityFailureCategory.CHUNK_INVALID)


__all__ = ["ChunkStabilitySummaryBuilder"]
