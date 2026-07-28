from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
    ConfluenceAclMaterializationResult,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    JiraRelationQualityObservation,
    copy_json_object,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
    ONE_PAGE_EXPORT_MODE,
    ONE_PAGE_SCHEMAS_VERSION,
    ONE_PAGE_SOURCE_ID,
    ONE_PAGE_SPACE_KEY,
    OnePageExportProfileBundle,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationValidationError,
)


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


class OnePageExportProjectionError(Exception):
    """A sanitized one-page export trusted-projection/graph-invariant failure."""

    def __init__(self) -> None:
        super().__init__("export_projection")


@dataclass(frozen=True, repr=False)
class OnePageExportProjection:
    """Frozen, ownership-isolated one-page export projection (spec §3-§6).

    Exactly the eight full-snapshot streams, contract-constant dataset/source/
    export/schema identity, deterministic source scopes, profile provenance,
    and the trusted Jira/ACL quality-and-metrics carried forward unchanged.
    ``repr`` is suppressed so record contents never render. The manifest-count
    invariant is deliberately not evaluated here (no ``Manifest`` is built by
    this stage; deferred to M6G-C).
    """

    dataset_name: str
    source_id: str
    export_mode: str
    schemas_version: str
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    acl: tuple[dict[str, object], ...]
    media_assets: tuple[dict[str, object], ...]
    symbols: tuple[dict[str, object], ...]
    sync_state: tuple[dict[str, object], ...]
    tombstones: tuple[dict[str, object], ...]
    source_scopes: dict[str, object]
    chunker_version: str
    active_profile: str
    profile_status: str
    config_hash: str
    jira_quality_observation: JiraRelationQualityObservation
    jira_metrics: dict[str, object]
    acl_quality_observation: AclQualityObservation
    acl_metrics: dict[str, object]

    def __post_init__(self) -> None:
        for name in (
            "dataset_name",
            "source_id",
            "export_mode",
            "schemas_version",
            "chunker_version",
            "active_profile",
            "profile_status",
            "config_hash",
        ):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} expects str")
        for name in (
            "documents",
            "chunks",
            "relations",
            "acl",
            "media_assets",
            "symbols",
            "sync_state",
            "tombstones",
        ):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)):
                raise TypeError(f"{name} expects a collection")
            records = tuple(value)
            if not all(isinstance(record, dict) for record in records):
                raise TypeError(f"{name} expects dict entries")
            object.__setattr__(
                self, name, tuple(copy_json_object(record) for record in records)
            )
        if not isinstance(self.source_scopes, dict):
            raise TypeError("source_scopes expects dict")
        if not isinstance(
            self.jira_quality_observation, JiraRelationQualityObservation
        ):
            raise TypeError(
                "jira_quality_observation expects JiraRelationQualityObservation"
            )
        if not isinstance(self.jira_metrics, dict):
            raise TypeError("jira_metrics expects dict")
        if not isinstance(self.acl_quality_observation, AclQualityObservation):
            raise TypeError(
                "acl_quality_observation expects AclQualityObservation"
            )
        if not isinstance(self.acl_metrics, dict):
            raise TypeError("acl_metrics expects dict")

        object.__setattr__(
            self, "source_scopes", copy_json_object(self.source_scopes)
        )
        object.__setattr__(self, "jira_metrics", copy_json_object(self.jira_metrics))
        object.__setattr__(self, "acl_metrics", copy_json_object(self.acl_metrics))
        jira_quality = self.jira_quality_observation
        object.__setattr__(
            self,
            "jira_quality_observation",
            JiraRelationQualityObservation(
                unique_key_like_candidates=jira_quality.unique_key_like_candidates,
                allowlisted_keys=jira_quality.allowlisted_keys,
                outside_allowlist_keys=jira_quality.outside_allowlist_keys,
            ),
        )


class ProjectOnePageExport:
    """Project one trusted M6F composition result into the one-page export shape.

    Consumes an already-trusted ``ConfluenceAclMaterializationResult`` and the
    deterministic ``OnePageExportProfileBundle``; recomputes nothing from M6F
    policy and never mutates its inputs. It does not stage, complete, publish,
    or write anything, and never imports the M3 exporter.
    """

    def __init__(self, *, schema_validator: _SchemaValidator) -> None:
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._schema_validator = schema_validator

    def execute(
        self,
        *,
        acl_result: ConfluenceAclMaterializationResult,
        profile_bundle: OnePageExportProfileBundle,
    ) -> OnePageExportProjection:
        if not isinstance(acl_result, ConfluenceAclMaterializationResult):
            raise TypeError(
                "acl_result expects ConfluenceAclMaterializationResult"
            )
        if not isinstance(profile_bundle, OnePageExportProfileBundle):
            raise TypeError("profile_bundle expects OnePageExportProfileBundle")

        before = deepcopy(acl_result)

        canonical = acl_result.enriched_canonical_document
        chunks = acl_result.enriched_chunks
        relations = acl_result.relations
        acl_record = acl_result.acl_record

        self._validate_canonical(canonical)
        self._validate_acl_record(acl_record=acl_record, canonical=canonical)
        self._validate_chunks(
            chunks=chunks, canonical=canonical, acl_record=acl_record
        )
        exported_relation_ids = self._validate_relations(
            relations=relations, canonical=canonical
        )
        self._validate_relation_resolution(
            chunks=chunks, exported_relation_ids=exported_relation_ids
        )
        self._validate_chunker_version(chunks=chunks, profile_bundle=profile_bundle)

        if acl_result != before:
            raise OnePageExportProjectionError()

        source_scopes = {
            "confluence": {
                "source_ids": [ONE_PAGE_SOURCE_ID],
                "space_keys": [canonical.get("space_key")],
                "page_ids": [canonical.get("page_id")],
            }
        }

        return OnePageExportProjection(
            dataset_name=ONE_PAGE_DATASET_NAME,
            source_id=ONE_PAGE_SOURCE_ID,
            export_mode=ONE_PAGE_EXPORT_MODE,
            schemas_version=ONE_PAGE_SCHEMAS_VERSION,
            documents=(canonical,),
            chunks=chunks,
            relations=relations,
            acl=(acl_record,),
            media_assets=(),
            symbols=(),
            sync_state=(),
            tombstones=(),
            source_scopes=source_scopes,
            chunker_version=profile_bundle.chunking_profile.chunker_version,
            active_profile=profile_bundle.chunking_profile.active_profile,
            profile_status=profile_bundle.chunking_profile.profile_status,
            config_hash=profile_bundle.config_hash,
            jira_quality_observation=acl_result.jira_quality_observation,
            jira_metrics=acl_result.jira_metrics,
            acl_quality_observation=acl_result.quality_observation,
            acl_metrics=acl_result.metrics,
        )

    def _validate_canonical(self, canonical: Mapping[str, object]) -> None:
        try:
            self._schema_validator.validate_record(
                "CanonicalDocument", canonical
            )
        except (FoundationValidationError, TypeError, ValueError):
            raise OnePageExportProjectionError() from None
        if canonical.get("source_system") != "confluence":
            raise OnePageExportProjectionError()
        if canonical.get("source_type") != "wiki_page":
            raise OnePageExportProjectionError()
        if canonical.get("space_key") != ONE_PAGE_SPACE_KEY:
            raise OnePageExportProjectionError()
        try:
            require_confluence_page_id(canonical.get("page_id"))
        except (TypeError, ValueError):
            raise OnePageExportProjectionError() from None

    def _validate_acl_record(
        self,
        *,
        acl_record: Mapping[str, object],
        canonical: Mapping[str, object],
    ) -> None:
        try:
            self._schema_validator.validate_record("ACLRecord", acl_record)
        except (FoundationValidationError, TypeError, ValueError):
            raise OnePageExportProjectionError() from None
        if acl_record.get("source_system") != "confluence":
            raise OnePageExportProjectionError()
        if acl_record.get("document_id") != canonical.get("document_id"):
            raise OnePageExportProjectionError()
        if acl_record.get("acl_id") != canonical.get("acl_id"):
            raise OnePageExportProjectionError()

    def _validate_chunks(
        self,
        *,
        chunks: tuple[Mapping[str, object], ...],
        canonical: Mapping[str, object],
        acl_record: Mapping[str, object],
    ) -> None:
        acl_tags = acl_record.get("acl_tags")
        seen_chunk_ids: set[str] = set()
        for chunk in chunks:
            try:
                self._schema_validator.validate_record("ChunkRecord", chunk)
            except (FoundationValidationError, TypeError, ValueError):
                raise OnePageExportProjectionError() from None
            if chunk.get("document_id") != canonical.get("document_id"):
                raise OnePageExportProjectionError()
            for field_name in ("source_system", "source_type", "space_key", "page_id"):
                if chunk.get(field_name) != canonical.get(field_name):
                    raise OnePageExportProjectionError()
            if chunk.get("acl_tags") != acl_tags:
                raise OnePageExportProjectionError()
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or chunk_id in seen_chunk_ids:
                raise OnePageExportProjectionError()
            seen_chunk_ids.add(chunk_id)

    def _validate_relations(
        self,
        *,
        relations: tuple[Mapping[str, object], ...],
        canonical: Mapping[str, object],
    ) -> tuple[str, ...]:
        document_id = canonical.get("document_id")
        canonical_relation_ids = canonical.get("relation_ids")
        if not isinstance(canonical_relation_ids, list):
            raise OnePageExportProjectionError()
        seen_relation_ids: set[str] = set()
        exported_ids: list[str] = []
        for relation in relations:
            try:
                self._schema_validator.validate_record("RelationRecord", relation)
            except (FoundationValidationError, TypeError, ValueError):
                raise OnePageExportProjectionError() from None
            if relation.get("source_id") != document_id:
                raise OnePageExportProjectionError()
            relation_id = relation.get("relation_id")
            if not isinstance(relation_id, str) or relation_id in seen_relation_ids:
                raise OnePageExportProjectionError()
            seen_relation_ids.add(relation_id)
            exported_ids.append(relation_id)
        if list(canonical_relation_ids) != exported_ids:
            raise OnePageExportProjectionError()
        return tuple(exported_ids)

    @staticmethod
    def _validate_relation_resolution(
        *,
        chunks: tuple[Mapping[str, object], ...],
        exported_relation_ids: tuple[str, ...],
    ) -> None:
        exported = set(exported_relation_ids)
        for chunk in chunks:
            relation_ids = chunk.get("relation_ids")
            if not isinstance(relation_ids, list):
                raise OnePageExportProjectionError()
            if any(relation_id not in exported for relation_id in relation_ids):
                raise OnePageExportProjectionError()

    @staticmethod
    def _validate_chunker_version(
        *,
        chunks: tuple[Mapping[str, object], ...],
        profile_bundle: OnePageExportProfileBundle,
    ) -> None:
        expected = profile_bundle.chunking_profile.chunker_version
        for chunk in chunks:
            if chunk.get("chunker_version") != expected:
                raise OnePageExportProjectionError()
