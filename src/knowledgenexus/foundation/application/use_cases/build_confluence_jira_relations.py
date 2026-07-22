from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_chunking import (
    ChunkingResult,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    ConfluenceJiraRelationError,
    ConfluenceJiraRelationFailureCategory,
    ConfluenceJiraRelationResult,
    JiraRelationQualityObservation,
    copy_json_object,
)
from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.rules import ContentHasher, TextNormalizationRules
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationValidationError,
)


_RELATION_TYPE = "mentions_jira_key"
_EVIDENCE = "regex:page_body"
_CONFIDENCE = 0.95
_RESOLUTION_STATUS = "unresolved_without_jira_api"
_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.[0-9]+)?"
    r"(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _RelationIdGenerator(Protocol):
    def generate_relation_id(
        self,
        source_id: str,
        relation_type: str,
        target_id: str,
    ) -> str: ...


class _DocumentIdGenerator(Protocol):
    def confluence_page_id(self, page_id: str) -> str: ...

    def source_entity_id(
        self,
        source_system: str,
        entity_kind: str,
        *stable_parts: str,
    ) -> str: ...


class _RelationRecordBuilder(Protocol):
    def build(self, **fields: object) -> dict[str, object]: ...


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


def _fail(category: ConfluenceJiraRelationFailureCategory) -> None:
    raise ConfluenceJiraRelationError(category) from None


class BuildConfluenceJiraRelations:
    """Extract and link deterministic page-level Jira relations."""

    def __init__(
        self,
        *,
        profile: JiraRelationProfile,
        document_id_generator: _DocumentIdGenerator,
        relation_id_generator: _RelationIdGenerator,
        relation_record_builder: _RelationRecordBuilder,
        schema_validator: _SchemaValidator,
    ) -> None:
        if not isinstance(profile, JiraRelationProfile):
            raise TypeError("profile expects JiraRelationProfile")
        if not callable(getattr(document_id_generator, "confluence_page_id", None)):
            raise TypeError("document_id_generator is invalid")
        if not callable(getattr(document_id_generator, "source_entity_id", None)):
            raise TypeError("document_id_generator is invalid")
        if not callable(
            getattr(relation_id_generator, "generate_relation_id", None)
        ):
            raise TypeError("relation_id_generator is invalid")
        if not callable(getattr(relation_record_builder, "build", None)):
            raise TypeError("relation_record_builder is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._profile = profile
        self._pattern = re.compile(profile.key_pattern)
        self._document_id_generator = document_id_generator
        self._relation_id_generator = relation_id_generator
        self._relation_record_builder = relation_record_builder
        self._schema_validator = schema_validator

    def execute(
        self,
        *,
        normalized_body_text: str,
        canonical_document: Mapping[str, object],
        chunking_result: ChunkingResult,
        created_at: str,
    ) -> ConfluenceJiraRelationResult:
        try:
            return self._execute(
                normalized_body_text=normalized_body_text,
                canonical_document=canonical_document,
                chunking_result=chunking_result,
                created_at=created_at,
            )
        except ConfluenceJiraRelationError:
            raise
        except Exception:
            _fail(
                ConfluenceJiraRelationFailureCategory.RELATION_EXTRACTION_FAILED
            )

    def _execute(
        self,
        *,
        normalized_body_text: str,
        canonical_document: Mapping[str, object],
        chunking_result: ChunkingResult,
        created_at: str,
    ) -> ConfluenceJiraRelationResult:
        self._validate_body(normalized_body_text)
        if not _is_rfc3339_timestamp(created_at):
            _fail(ConfluenceJiraRelationFailureCategory.INVALID_CREATED_AT)
        if not isinstance(canonical_document, Mapping):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        if not isinstance(chunking_result, ChunkingResult):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
            )

        try:
            canonical_before = copy_json_object(dict(canonical_document))
        except (TypeError, ValueError):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        try:
            chunks_before = tuple(
                copy_json_object(record) for record in chunking_result.records
            )
        except (TypeError, ValueError):
            _fail(ConfluenceJiraRelationFailureCategory.CHUNK_RECORD_INVALID)
        self._validate_canonical(
            normalized_body_text=normalized_body_text,
            canonical_document=canonical_document,
        )
        self._validate_chunks(
            canonical_document=canonical_document,
            chunking_result=chunking_result,
        )

        occurrences = tuple(
            match.group("key") for match in self._pattern.finditer(normalized_body_text)
        )
        unique_candidates = _unique_in_order(occurrences)
        allowed_projects = set(self._profile.allowed_project_keys)
        allowlisted = tuple(
            key for key in unique_candidates if key.rsplit("-", 1)[0] in allowed_projects
        )
        outside = tuple(
            key for key in unique_candidates if key.rsplit("-", 1)[0] not in allowed_projects
        )

        source_id = canonical_document["document_id"]
        if not isinstance(source_id, str):  # guarded by schema and identity checks
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        relations, relation_ids, target_ids = self._build_relations(
            source_id=source_id,
            jira_keys=allowlisted,
            created_at=created_at,
        )
        enriched_document = copy_json_object(dict(canonical_document))
        enriched_document["jira_keys"] = list(allowlisted)
        enriched_document["relation_ids"] = list(relation_ids)
        enriched_chunks = tuple(
            self._enrich_chunk(record, allowlisted, relation_ids)
            for record in chunking_result.records
        )

        self._validate_enriched(
            canonical_document=enriched_document,
            chunks=enriched_chunks,
        )
        metrics = {
            "candidate_occurrences": len(occurrences),
            "unique_key_like_count": len(unique_candidates),
            "allowlisted_unique_count": len(allowlisted),
            "outside_allowlist_unique_count": len(outside),
            "duplicate_occurrences": len(occurrences) - len(unique_candidates),
            "relations_total": len(relations),
            "documents_enriched": 1 if relations else 0,
            "chunks_enriched": len(enriched_chunks) if relations else 0,
        }
        self._validate_cross_references(
            canonical_document=enriched_document,
            chunks=enriched_chunks,
            relations=relations,
            jira_keys=allowlisted,
            relation_ids=relation_ids,
            target_ids=target_ids,
            canonical_before=canonical_before,
            chunks_before=chunks_before,
        )
        if dict(canonical_document) != canonical_before or tuple(
            chunking_result.records
        ) != chunks_before:
            _fail(
                ConfluenceJiraRelationFailureCategory.RELATION_CROSS_REFERENCE_INVALID
            )

        return ConfluenceJiraRelationResult(
            enriched_canonical_document=enriched_document,
            enriched_chunks=enriched_chunks,
            relations=relations,
            quality_observation=JiraRelationQualityObservation(
                unique_key_like_candidates=unique_candidates,
                allowlisted_keys=allowlisted,
                outside_allowlist_keys=outside,
            ),
            metrics=metrics,
        )

    @staticmethod
    def _validate_body(normalized_body_text: object) -> None:
        if not isinstance(normalized_body_text, str):
            _fail(
                ConfluenceJiraRelationFailureCategory.INVALID_NORMALIZED_BODY
            )
        try:
            canonical = TextNormalizationRules.normalize_text(normalized_body_text)
        except (TypeError, ValueError):
            _fail(
                ConfluenceJiraRelationFailureCategory.INVALID_NORMALIZED_BODY
            )
        if canonical != normalized_body_text:
            _fail(
                ConfluenceJiraRelationFailureCategory.INVALID_NORMALIZED_BODY
            )

    def _validate_canonical(
        self,
        *,
        normalized_body_text: str,
        canonical_document: Mapping[str, object],
    ) -> None:
        try:
            self._schema_validator.validate_record(
                "CanonicalDocument", canonical_document
            )
        except (FoundationValidationError, TypeError, ValueError):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        if (
            canonical_document.get("source_system") != "confluence"
            or canonical_document.get("source_type") != "wiki_page"
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        page_id = canonical_document.get("page_id")
        try:
            page_id = require_confluence_page_id(page_id)
            expected_document_id = self._document_id_generator.confluence_page_id(
                page_id
            )
        except (TypeError, ValueError):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        if canonical_document.get("document_id") != expected_document_id:
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        if not isinstance(canonical_document.get("source_version"), str) or not (
            canonical_document.get("source_version")
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
            )
        if (
            "jira_keys" not in canonical_document
            or "relation_ids" not in canonical_document
            or canonical_document.get("jira_keys") != []
            or canonical_document.get("relation_ids") != []
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.RELATION_STAGE_INPUT_NOT_PRISTINE
            )
        content_hash = canonical_document.get("content_hash")
        if (
            not isinstance(content_hash, str)
            or content_hash != ContentHasher.hash_text(normalized_body_text)
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.NORMALIZED_BODY_CONTENT_HASH_MISMATCH
            )

    def _validate_chunks(
        self,
        *,
        canonical_document: Mapping[str, object],
        chunking_result: ChunkingResult,
    ) -> None:
        chunks_total = chunking_result.metrics.get("chunks_total")
        chunks_over = chunking_result.metrics.get("chunks_over_hard_max")
        if (
            isinstance(chunks_total, bool)
            or not isinstance(chunks_total, int)
            or chunks_total != len(chunking_result.records)
            or chunks_over != 0
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
            )
        seen_chunk_ids: set[str] = set()
        copied_fields = (
            "document_id",
            "source_system",
            "source_type",
            "title",
            "space_key",
            "page_id",
            "source_version",
            "updated_at",
        )
        for chunk in chunking_result.records:
            try:
                self._schema_validator.validate_record("ChunkRecord", chunk)
            except (FoundationValidationError, TypeError, ValueError):
                _fail(
                    ConfluenceJiraRelationFailureCategory.CHUNK_RECORD_INVALID
                )
            if (
                "jira_keys" not in chunk
                or "relation_ids" not in chunk
                or chunk.get("jira_keys") != []
                or chunk.get("relation_ids") != []
            ):
                _fail(
                    ConfluenceJiraRelationFailureCategory.RELATION_STAGE_INPUT_NOT_PRISTINE
                )
            if any(
                chunk.get(field) != canonical_document.get(field)
                for field in copied_fields
            ):
                _fail(
                    ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
                )
            chunk_id = chunk.get("chunk_id")
            text = chunk.get("text")
            if (
                not isinstance(chunk_id, str)
                or chunk_id in seen_chunk_ids
                or not isinstance(text, str)
                or chunk.get("content_hash") != ContentHasher.hash_text(text)
            ):
                _fail(
                    ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
                )
            seen_chunk_ids.add(chunk_id)

    def _build_relations(
        self,
        *,
        source_id: str,
        jira_keys: tuple[str, ...],
        created_at: str,
    ) -> tuple[
        tuple[dict[str, object], ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        records: list[dict[str, object]] = []
        relation_ids: list[str] = []
        target_ids: list[str] = []
        seen_preimages: dict[str, tuple[str, str, str]] = {}
        for jira_key in jira_keys:
            try:
                target_id = self._document_id_generator.source_entity_id(
                    "jira", "issue", jira_key
                )
                preimage = (source_id, _RELATION_TYPE, target_id)
                relation_id = self._relation_id_generator.generate_relation_id(
                    *preimage
                )
            except (TypeError, ValueError):
                _fail(
                    ConfluenceJiraRelationFailureCategory.RELATION_EXTRACTION_FAILED
                )
            previous = seen_preimages.get(relation_id)
            if previous is not None and previous != preimage:
                _fail(
                    ConfluenceJiraRelationFailureCategory.RELATION_ID_COLLISION
                )
            seen_preimages[relation_id] = preimage
            try:
                record = self._relation_record_builder.build(
                    relation_id=relation_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=_RELATION_TYPE,
                    evidence=_EVIDENCE,
                    confidence=_CONFIDENCE,
                    resolution_status=_RESOLUTION_STATUS,
                    created_at=created_at,
                )
                self._schema_validator.validate_record("RelationRecord", record)
            except (FoundationValidationError, TypeError, ValueError):
                _fail(
                    ConfluenceJiraRelationFailureCategory.RELATION_RECORD_VALIDATION_FAILED
                )
            records.append(record)
            relation_ids.append(relation_id)
            target_ids.append(target_id)
        return tuple(records), tuple(relation_ids), tuple(target_ids)

    @staticmethod
    def _enrich_chunk(
        chunk: dict[str, object],
        jira_keys: tuple[str, ...],
        relation_ids: tuple[str, ...],
    ) -> dict[str, object]:
        copied = copy_json_object(chunk)
        copied["jira_keys"] = list(jira_keys)
        copied["relation_ids"] = list(relation_ids)
        return copied

    def _validate_enriched(
        self,
        *,
        canonical_document: dict[str, object],
        chunks: tuple[dict[str, object], ...],
    ) -> None:
        try:
            self._schema_validator.validate_record(
                "CanonicalDocument", canonical_document
            )
        except (FoundationValidationError, TypeError, ValueError):
            _fail(
                ConfluenceJiraRelationFailureCategory.ENRICHED_DOCUMENT_VALIDATION_FAILED
            )
        for chunk in chunks:
            try:
                self._schema_validator.validate_record("ChunkRecord", chunk)
            except (FoundationValidationError, TypeError, ValueError):
                _fail(
                    ConfluenceJiraRelationFailureCategory.ENRICHED_CHUNK_VALIDATION_FAILED
                )

    @staticmethod
    def _validate_cross_references(
        *,
        canonical_document: dict[str, object],
        chunks: tuple[dict[str, object], ...],
        relations: tuple[dict[str, object], ...],
        jira_keys: tuple[str, ...],
        relation_ids: tuple[str, ...],
        target_ids: tuple[str, ...],
        canonical_before: dict[str, object],
        chunks_before: tuple[dict[str, object], ...],
    ) -> None:
        expected_keys = list(jira_keys)
        expected_ids = list(relation_ids)
        source_id = canonical_document.get("document_id")
        if (
            canonical_document.get("jira_keys") != expected_keys
            or canonical_document.get("relation_ids") != expected_ids
            or [record.get("relation_id") for record in relations] != expected_ids
            or any(record.get("source_id") != source_id for record in relations)
            or len(target_ids) != len(jira_keys)
            or [record.get("target_id") for record in relations]
            != list(target_ids)
            or any(chunk.get("jira_keys") != expected_keys for chunk in chunks)
            or any(chunk.get("relation_ids") != expected_ids for chunk in chunks)
            or len(chunks) != len(chunks_before)
        ):
            _fail(
                ConfluenceJiraRelationFailureCategory.RELATION_CROSS_REFERENCE_INVALID
            )
        canonical_without_links = copy_json_object(canonical_document)
        canonical_without_links["jira_keys"] = []
        canonical_without_links["relation_ids"] = []
        if canonical_without_links != canonical_before:
            _fail(
                ConfluenceJiraRelationFailureCategory.RELATION_CROSS_REFERENCE_INVALID
            )
        for enriched, original in zip(chunks, chunks_before, strict=True):
            without_links = copy_json_object(enriched)
            without_links["jira_keys"] = []
            without_links["relation_ids"] = []
            if without_links != original:
                _fail(
                    ConfluenceJiraRelationFailureCategory.RELATION_CROSS_REFERENCE_INVALID
                )


def _unique_in_order(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


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
