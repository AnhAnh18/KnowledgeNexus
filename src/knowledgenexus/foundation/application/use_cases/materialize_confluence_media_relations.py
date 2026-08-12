from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from knowledgenexus.foundation.domain.models.media_materialization import (
    MediaMaterializationResult,
)
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.records.relation_record_builder import (
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.rules.relation_id_generator import (
    RelationIdGenerator,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class MediaRelationMaterializationFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    MISSING_SOURCE = "missing_source"
    CROSS_PAGE = "cross_page"
    DUPLICATE_ID = "duplicate_id"
    SCHEMA_INVALID = "schema_invalid"


class MediaRelationMaterializationError(Exception):
    """Sanitized failure for the pure media-relation projection boundary."""

    def __init__(self, category: MediaRelationMaterializationFailureCategory) -> None:
        if not isinstance(category, MediaRelationMaterializationFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)


class _SchemaValidatorPort(Protocol):
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None: ...


@dataclass(frozen=True)
class MediaRelationMaterializationMetrics:
    relations_total: int
    resolved: int
    unresolved_target: int
    documents_enriched: int
    chunks_enriched: int

    def __post_init__(self) -> None:
        values = (
            self.relations_total,
            self.resolved,
            self.unresolved_target,
            self.documents_enriched,
            self.chunks_enriched,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("media relation metrics are invalid")
        if self.resolved + self.unresolved_target != self.relations_total:
            raise ValueError("media relation status counts are inconsistent")
        if self.documents_enriched > self.relations_total:
            raise ValueError("media relation enrichment counts are inconsistent")


@dataclass(frozen=True)
class MediaRelationMaterializationResult:
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    metrics: MediaRelationMaterializationMetrics

    def __post_init__(self) -> None:
        if type(self.documents) is not tuple or type(self.chunks) is not tuple or type(self.relations) is not tuple:
            raise TypeError("materialization records must be tuples")
        if any(type(record) is not dict for record in (*self.documents, *self.chunks, *self.relations)):
            raise TypeError("materialization records are invalid")
        if type(self.metrics) is not MediaRelationMaterializationMetrics:
            raise TypeError("metrics are invalid")
        if len(self.relations) != self.metrics.relations_total:
            raise ValueError("relation count does not match metrics")
        object.__setattr__(self, "documents", tuple(copy.deepcopy(record) for record in self.documents))
        object.__setattr__(self, "chunks", tuple(copy.deepcopy(record) for record in self.chunks))
        object.__setattr__(self, "relations", tuple(copy.deepcopy(record) for record in self.relations))


def _fail(category: MediaRelationMaterializationFailureCategory) -> None:
    raise MediaRelationMaterializationError(category)


def _record_id(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if type(value) is not str or not value:
        _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
    return value


def _unresolved_target(source_id: str, evidence: str) -> str:
    digest = hashlib.sha256(f"{source_id}\x1f{evidence}".encode("utf-8")).hexdigest()[:16]
    return f"confluence:attachment:unresolved-{digest}"


def _unresolved_page_target(source_id: str, evidence: str) -> str:
    digest = hashlib.sha256(f"{source_id}\x1f{evidence}".encode("utf-8")).hexdigest()[:16]
    return f"confluence:page:unresolved-{digest}"


class MaterializeConfluenceMediaRelations:
    """Turn normalized media intents into generic M10 relation records.

    This stage is deliberately separate from the Jira relation path. It keeps
    the MVP media boundary metadata-first while making page ownership explicit
    to downstream indexing through ``embeds_media`` and ``relation_ids``.
    """

    def __init__(self, *, schema_validator: object | None = None) -> None:
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._validator: _SchemaValidatorPort = validator

    def execute(
        self,
        *,
        documents: object,
        chunks: object,
        media: object,
        page_references: object = (),
        page_targets: object = (),
    ) -> MediaRelationMaterializationResult:
        if type(documents) is not tuple or type(chunks) is not tuple or type(media) is not MediaMaterializationResult:
            _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
        if type(page_references) is not tuple or type(page_targets) is not tuple:
            _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
        if any(type(record) is not dict for record in (*documents, *chunks)):
            _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
        try:
            trusted_media = MediaMaterializationResult(
                assets=tuple(copy.deepcopy(media.assets)),
                relation_intents=tuple(media.relation_intents),
            )
        except Exception:
            _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)

        output_documents = [copy.deepcopy(record) for record in documents]
        output_chunks = [copy.deepcopy(record) for record in chunks]
        document_by_id: dict[str, dict[str, object]] = {}
        for record in output_documents:
            document_id = _record_id(record, "document_id")
            if document_id in document_by_id:
                _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
            document_by_id[document_id] = record
        chunk_ids: set[str] = set()
        for record in output_chunks:
            chunk_id = _record_id(record, "chunk_id")
            if chunk_id in chunk_ids:
                _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
            chunk_ids.add(chunk_id)
            _record_id(record, "document_id")

        assets_by_id: dict[str, dict[str, object]] = {}
        for asset in trusted_media.assets:
            media_id = _record_id(asset, "media_id")
            if media_id in assets_by_id:
                _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
            assets_by_id[media_id] = asset

        page_reference_map: dict[str, tuple[NormalizationReferenceIntent, ...]] = {}
        for entry in page_references:
            if type(entry) is not tuple or len(entry) != 2:
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            source_id, intents = entry
            if type(source_id) is not str or source_id not in document_by_id:
                _fail(MediaRelationMaterializationFailureCategory.MISSING_SOURCE)
            if type(intents) is not tuple or any(type(intent) is not NormalizationReferenceIntent for intent in intents):
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            if tuple(intent.ordinal for intent in intents) != tuple(range(1, len(intents) + 1)):
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            if source_id in page_reference_map:
                _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
            page_reference_map[source_id] = intents
        page_target_map: dict[str, str] = {}
        for entry in page_targets:
            if type(entry) is not tuple or len(entry) != 2:
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            identity, target_id = entry
            if type(identity) is not str or type(target_id) is not str or not identity or target_id not in document_by_id or not target_id.startswith("confluence:page:"):
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            if page_target_map.get(identity) not in {None, target_id}:
                _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
            page_target_map[identity] = target_id

        relations: list[dict[str, object]] = []
        relation_ids_by_document: dict[str, set[str]] = {}
        resolved = 0
        unresolved = 0
        for intent in trusted_media.relation_intents:
            source_id = intent.source_document_id
            source = document_by_id.get(source_id)
            if source is None:
                _fail(MediaRelationMaterializationFailureCategory.MISSING_SOURCE)
            target_id = intent.target_media_id
            status = "resolved"
            if target_id is None:
                target_id = _unresolved_target(source_id, intent.evidence)
                status = "unresolved_target"
                unresolved += 1
            else:
                asset = assets_by_id.get(target_id)
                if asset is None:
                    _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
                if asset.get("parent_document_id") != source_id:
                    _fail(MediaRelationMaterializationFailureCategory.CROSS_PAGE)
                resolved += 1
            created_at = source.get("crawled_at")
            if type(created_at) is not str or not created_at:
                _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
            relation_id = RelationIdGenerator.generate_relation_id(source_id, "embeds_media", target_id)
            record = RelationRecordBuilder.build(
                relation_id=relation_id,
                source_id=source_id,
                target_id=target_id,
                relation_type="embeds_media",
                resolution_status=status,
                created_at=created_at,
                evidence=intent.evidence,
            )
            self._validate("RelationRecord", record)
            relations.append(record)
            relation_ids_by_document.setdefault(source_id, set()).add(relation_id)

        for source_id, intents in page_reference_map.items():
            source = document_by_id[source_id]
            for intent in intents:
                if intent.kind not in {"include_page", "page_link"}:
                    continue
                relation_type = "includes_page" if intent.kind == "include_page" else "links_to_page"
                target_id = page_target_map.get(intent.target_identity)
                if target_id is None and intent.target_identity.startswith("confluence:page:"):
                    target_id = intent.target_identity if intent.target_identity in document_by_id else None
                status = "resolved"
                if target_id is None:
                    target_id = _unresolved_page_target(source_id, intent.target_identity)
                    status = "unresolved_target"
                    unresolved += 1
                else:
                    resolved += 1
                created_at = source.get("crawled_at")
                if type(created_at) is not str or not created_at:
                    _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
                relation_id = RelationIdGenerator.generate_relation_id(source_id, relation_type, target_id)
                record = RelationRecordBuilder.build(
                    relation_id=relation_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                    resolution_status=status,
                    created_at=created_at,
                    evidence=intent.target_identity,
                )
                self._validate("RelationRecord", record)
                relations.append(record)
                relation_ids_by_document.setdefault(source_id, set()).add(relation_id)

        for record in output_documents:
            document_id = _record_id(record, "document_id")
            ids = self._merge_relation_ids(record, relation_ids_by_document.get(document_id, set()))
            if ids:
                record["relation_ids"] = ids
        enriched_chunks = 0
        for record in output_chunks:
            document_id = _record_id(record, "document_id")
            ids = relation_ids_by_document.get(document_id, set())
            if ids:
                record["relation_ids"] = self._merge_relation_ids(record, ids)
                enriched_chunks += 1

        for record in output_documents:
            self._validate("CanonicalDocument", record)
        for record in output_chunks:
            self._validate("ChunkRecord", record)
        relations.sort(key=lambda record: _record_id(record, "relation_id"))
        metrics = MediaRelationMaterializationMetrics(
            relations_total=len(relations),
            resolved=resolved,
            unresolved_target=unresolved,
            documents_enriched=len(relation_ids_by_document),
            chunks_enriched=enriched_chunks,
        )
        return MediaRelationMaterializationResult(
            documents=tuple(output_documents),
            chunks=tuple(output_chunks),
            relations=tuple(relations),
            metrics=metrics,
        )

    @staticmethod
    def _merge_relation_ids(record: dict[str, object], additions: set[str]) -> list[str]:
        existing = record.get("relation_ids", [])
        if type(existing) is not list or any(type(value) is not str or not value for value in existing):
            _fail(MediaRelationMaterializationFailureCategory.INVALID_INPUT)
        if len(existing) != len(set(existing)):
            _fail(MediaRelationMaterializationFailureCategory.DUPLICATE_ID)
        merged = set(existing) | set(additions)
        return sorted(merged)

    def _validate(self, schema_name: str, record: dict[str, object]) -> None:
        try:
            self._validator.validate_record(schema_name, record)
        except Exception:
            _fail(MediaRelationMaterializationFailureCategory.SCHEMA_INVALID)


__all__ = [
    "MaterializeConfluenceMediaRelations",
    "MediaRelationMaterializationError",
    "MediaRelationMaterializationFailureCategory",
    "MediaRelationMaterializationMetrics",
    "MediaRelationMaterializationResult",
]
