from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    ConfluenceJiraRelationResult,
)
from knowledgenexus.foundation.domain.rules.acl_id_generator import (
    AclIdGenerator,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.domain.rules.content_hasher import ContentHasher
from knowledgenexus.foundation.domain.rules.document_id_generator import (
    DocumentIdGenerator,
)
from knowledgenexus.foundation.domain.rules.relation_id_generator import (
    RelationIdGenerator,
)

_RELATION_TYPE = "mentions_jira_key"
_EVIDENCE = "regex:page_body"
_CONFIDENCE = 0.95
_RESOLUTION_STATUS = "unresolved_without_jira_api"
_SCHEMA_VERSION = "1.0"
_PRISTINE_ACL_TAGS = ["restricted:unresolved"]
_CANONICAL_CHUNK_FIELDS = (
    "document_id",
    "source_system",
    "source_type",
    "title",
    "space_key",
    "page_id",
    "source_version",
    "updated_at",
)
_METRIC_KEYS = frozenset(
    {
        "candidate_occurrences",
        "unique_key_like_count",
        "allowlisted_unique_count",
        "outside_allowlist_unique_count",
        "duplicate_occurrences",
        "relations_total",
        "documents_enriched",
        "chunks_enriched",
    }
)

_Category = AclMaterializationFailureCategory


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


def _fail(category: AclMaterializationFailureCategory) -> None:
    raise AclMaterializationError(category) from None


class AclRelationInputValidator:
    """Validate the full approved M6E ``ConfluenceJiraRelationResult``.

    This is a pure provenance boundary for M6F. It re-verifies the enriched
    CanonicalDocument, enriched ChunkRecords, RelationRecords, quality
    observation, and metrics against the existing deterministic generators and
    the injected Foundation schema validator. It mutates nothing, builds no
    ``ACLRecord``, and never exposes source values in failures.
    """

    def __init__(self, *, schema_validator: _SchemaValidator) -> None:
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._schema_validator = schema_validator

    def validate(self, result: ConfluenceJiraRelationResult) -> None:
        if not isinstance(result, ConfluenceJiraRelationResult):
            raise TypeError("result expects ConfluenceJiraRelationResult")
        try:
            self._validate(result)
        except AclMaterializationError:
            raise
        except Exception:
            _fail(_Category.ACL_MATERIALIZATION_FAILED)

    def _validate(self, result: ConfluenceJiraRelationResult) -> None:
        canonical = result.enriched_canonical_document
        jira_keys, relation_ids = self._validate_canonical(canonical)
        self._validate_chunks(
            canonical=canonical,
            chunks=result.enriched_chunks,
            jira_keys=jira_keys,
            relation_ids=relation_ids,
        )
        self._validate_relations(
            canonical=canonical,
            relations=result.relations,
            jira_keys=jira_keys,
            relation_ids=relation_ids,
        )
        self._validate_quality(
            quality=result.quality_observation,
            jira_keys=jira_keys,
        )
        self._validate_metrics(result)

    def _validate_canonical(
        self, canonical: Mapping[str, object]
    ) -> tuple[list[object], list[object]]:
        try:
            self._schema_validator.validate_record(
                "CanonicalDocument", canonical
            )
        except (TypeError, ValueError):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        if (
            canonical.get("source_system") != "confluence"
            or canonical.get("source_type") != "wiki_page"
        ):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        try:
            page_id = require_confluence_page_id(canonical.get("page_id"))
            expected_document_id = DocumentIdGenerator.confluence_page_id(
                page_id
            )
        except (TypeError, ValueError):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        document_id = canonical.get("document_id")
        if document_id != expected_document_id:
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        assert isinstance(document_id, str)
        try:
            expected_acl_id = AclIdGenerator.generate_acl_id(document_id)
        except (TypeError, ValueError):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        if canonical.get("acl_id") != expected_acl_id:
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        source_version = canonical.get("source_version")
        if not isinstance(source_version, str) or source_version == "":
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        if "jira_keys" not in canonical or "relation_ids" not in canonical:
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        jira_keys = canonical.get("jira_keys")
        relation_ids = canonical.get("relation_ids")
        if not isinstance(jira_keys, list) or not isinstance(relation_ids, list):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        if _has_duplicate(jira_keys) or _has_duplicate(relation_ids):
            _fail(_Category.CANONICAL_DOCUMENT_INVALID)
        return jira_keys, relation_ids

    def _validate_chunks(
        self,
        *,
        canonical: Mapping[str, object],
        chunks: tuple[Mapping[str, object], ...],
        jira_keys: list[object],
        relation_ids: list[object],
    ) -> None:
        seen_chunk_ids: set[str] = set()
        for chunk in chunks:
            try:
                self._schema_validator.validate_record("ChunkRecord", chunk)
            except (TypeError, ValueError):
                _fail(_Category.CHUNK_RECORD_INVALID)
            if "jira_keys" not in chunk or "relation_ids" not in chunk:
                _fail(_Category.CANONICAL_CHUNK_IDENTITY_MISMATCH)
            if (
                chunk.get("jira_keys") != jira_keys
                or chunk.get("relation_ids") != relation_ids
            ):
                _fail(_Category.CANONICAL_CHUNK_IDENTITY_MISMATCH)
            if any(
                chunk.get(field) != canonical.get(field)
                for field in _CANONICAL_CHUNK_FIELDS
            ):
                _fail(_Category.CANONICAL_CHUNK_IDENTITY_MISMATCH)
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id in seen_chunk_ids:
                _fail(_Category.CANONICAL_CHUNK_IDENTITY_MISMATCH)
            text = chunk.get("text")
            if not isinstance(text, str):
                _fail(_Category.CHUNK_RECORD_INVALID)
            if chunk.get("content_hash") != ContentHasher.hash_text(text):
                _fail(_Category.CANONICAL_CHUNK_IDENTITY_MISMATCH)
            if chunk.get("acl_tags") != _PRISTINE_ACL_TAGS:
                _fail(_Category.ACL_STAGE_INPUT_NOT_PRISTINE)
            seen_chunk_ids.add(chunk_id)

    def _validate_relations(
        self,
        *,
        canonical: Mapping[str, object],
        relations: tuple[Mapping[str, object], ...],
        jira_keys: list[object],
        relation_ids: list[object],
    ) -> None:
        if not (len(jira_keys) == len(relation_ids) == len(relations)):
            _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)
        document_id = canonical.get("document_id")
        assert isinstance(document_id, str)
        for index, jira_key in enumerate(jira_keys):
            if not isinstance(jira_key, str):
                _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)
            try:
                expected_target_id = DocumentIdGenerator.source_entity_id(
                    "jira", "issue", jira_key
                )
                expected_relation_id = (
                    RelationIdGenerator.generate_relation_id(
                        document_id, _RELATION_TYPE, expected_target_id
                    )
                )
            except (TypeError, ValueError):
                _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)
            if relation_ids[index] != expected_relation_id:
                _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)
            record = relations[index]
            try:
                self._schema_validator.validate_record("RelationRecord", record)
            except (TypeError, ValueError):
                _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)
            if (
                record.get("schema_version") != _SCHEMA_VERSION
                or record.get("source_id") != document_id
                or record.get("target_id") != expected_target_id
                or record.get("relation_id") != expected_relation_id
                or record.get("relation_type") != _RELATION_TYPE
                or record.get("evidence") != _EVIDENCE
                or record.get("confidence") != _CONFIDENCE
                or record.get("resolution_status") != _RESOLUTION_STATUS
            ):
                _fail(_Category.M6E_RELATION_PROVENANCE_INVALID)

    def _validate_quality(
        self, *, quality: object, jira_keys: list[object]
    ) -> None:
        unique = getattr(quality, "unique_key_like_candidates", None)
        allow = getattr(quality, "allowlisted_keys", None)
        outside = getattr(quality, "outside_allowlist_keys", None)
        if not (
            isinstance(unique, tuple)
            and isinstance(allow, tuple)
            and isinstance(outside, tuple)
        ):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        for collection in (unique, allow, outside):
            if any(
                not isinstance(entry, str) or entry == ""
                for entry in collection
            ):
                _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
            if _has_duplicate(list(collection)):
                _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        if tuple(allow) != tuple(jira_keys):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        allow_set = set(allow)
        outside_set = set(outside)
        if allow_set & outside_set:
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        if allow_set | outside_set != set(unique):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        if len(allow) + len(outside) != len(unique):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        rebuilt_allow = tuple(key for key in unique if key in allow_set)
        rebuilt_outside = tuple(key for key in unique if key in outside_set)
        if rebuilt_allow != tuple(allow) or rebuilt_outside != tuple(outside):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)

    def _validate_metrics(self, result: ConfluenceJiraRelationResult) -> None:
        metrics = result.metrics
        if not isinstance(metrics, Mapping):
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        if set(metrics.keys()) != _METRIC_KEYS:
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        for value in metrics.values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)

        quality = result.quality_observation
        relations = result.relations
        derived = {
            "unique_key_like_count": len(quality.unique_key_like_candidates),
            "allowlisted_unique_count": len(quality.allowlisted_keys),
            "outside_allowlist_unique_count": len(
                quality.outside_allowlist_keys
            ),
            "relations_total": len(relations),
            "documents_enriched": 1 if relations else 0,
            "chunks_enriched": (
                len(result.enriched_chunks) if relations else 0
            ),
        }
        for key, expected in derived.items():
            if metrics[key] != expected:
                _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)

        candidate = metrics["candidate_occurrences"]
        unique_count = metrics["unique_key_like_count"]
        if candidate < unique_count:
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)
        if metrics["duplicate_occurrences"] != candidate - unique_count:
            _fail(_Category.M6E_RESULT_PROVENANCE_INVALID)


def _has_duplicate(values: list[object]) -> bool:
    seen: list[object] = []
    for value in values:
        if value in seen:
            return True
        seen.append(value)
    return False
