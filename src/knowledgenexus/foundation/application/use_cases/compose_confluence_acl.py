from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.application.use_cases.build_confluence_chunks import (
    BuildConfluenceChunks,
)
from knowledgenexus.foundation.application.use_cases.build_confluence_jira_relations import (
    BuildConfluenceJiraRelations,
)
from knowledgenexus.foundation.application.use_cases.materialize_confluence_acl import (
    MaterializeConfluenceAcl,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    CATEGORY_INVALID_PAGE_ID,
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationError,
)
from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    ConfluenceAclMaterializationResult,
)
from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.confluence_acl_composition import (
    ConfluenceAclCompositionAcceptanceError,
    ConfluenceAclCompositionResult,
    ConfluenceAclRestrictionAncestryError,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    ConfluenceJiraRelationResult,
)
from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.records.chunk_record_builder import (
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.records.relation_record_builder import (
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.rules.acl_restriction_observations import (
    validate_restriction_observations,
)
from knowledgenexus.foundation.domain.rules.chunk_id_generator import (
    ChunkIdGenerator,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_observations import (
    ConfluencePageObservationPayloadError,
    extract_ordered_restriction_targets,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import (
    DocumentIdGenerator,
)
from knowledgenexus.foundation.domain.rules.relation_id_generator import (
    RelationIdGenerator,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMapperPort,
    ConfluenceStorageNormalizerPort,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
    RawPageReadPort,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


@dataclass(frozen=True, repr=False)
class _FixedRawPageReader(RawPageReadPort):
    """A ``RawPageReadPort`` bound to one already-validated page/byte snapshot.

    The composition boundary never reads the filesystem or network itself; it
    only replays the exact preserved bytes the caller already trusts.
    """

    expected_page_id: str
    raw_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.raw_bytes, bytes):
            raise TypeError("raw_bytes expects bytes")
        object.__setattr__(self, "raw_bytes", bytes(self.raw_bytes))

    def read_page(self, *, page_id: str) -> bytes:
        if page_id != self.expected_page_id:
            raise RawPageReadError("raw page identity does not match")
        return self.raw_bytes


def _chunks_equal_except_acl(
    before: Sequence[Mapping[str, object]],
    after: Sequence[Mapping[str, object]],
) -> bool:
    if len(before) != len(after):
        return False
    for trusted, enriched in zip(before, after, strict=True):
        trusted_copy = dict(trusted)
        enriched_copy = dict(enriched)
        trusted_copy.pop("acl_tags", None)
        enriched_copy.pop("acl_tags", None)
        if trusted_copy != enriched_copy:
            return False
    return True


def _bind_restriction_ancestry(
    *,
    observations_copy: object,
    canonical_page_id: object,
    raw_page_bytes: bytes,
    selected_page_id: str,
) -> tuple[dict[str, object], ...]:
    try:
        validated = validate_restriction_observations(
            observations_copy,
            canonical_page_id=canonical_page_id,
        )
        expected_targets = extract_ordered_restriction_targets(
            raw_page=raw_page_bytes,
            selected_page_id=selected_page_id,
        )
    except (
        AclMaterializationError,
        ConfluencePageObservationPayloadError,
        TypeError,
        ValueError,
    ):
        raise ConfluenceAclRestrictionAncestryError() from None

    observed_targets = tuple(
        str(observation["source_page_id"]) for observation in validated
    )
    if observed_targets != expected_targets:
        raise ConfluenceAclRestrictionAncestryError()
    return validated


class ComposeConfluenceAcl:
    """Reusable M6A-through-M6F one-page composition boundary (M6G-B).

    Produces one ownership-isolated, contract-validated, deterministic
    in-memory ``ConfluenceAclCompositionResult`` from one trusted preserved raw
    page and its normalized restriction observation chain. It never accepts a
    filesystem path, external evidence bundle, evidence kind, credential,
    clock, store, transport, or connector, and never performs network or
    filesystem I/O itself; it only composes the existing approved
    M6C-through-M6F boundaries.
    """

    def __init__(
        self,
        *,
        chunking_profile: ChunkingProfile,
        jira_relation_profile: JiraRelationProfile,
        tokenizer: TokenizerPort,
        raw_page_mapper: ConfluenceRawPageMapperPort,
        storage_normalizer: ConfluenceStorageNormalizerPort,
        schema_validator: _SchemaValidator,
    ) -> None:
        if not isinstance(chunking_profile, ChunkingProfile):
            raise TypeError("chunking_profile expects ChunkingProfile")
        if not isinstance(jira_relation_profile, JiraRelationProfile):
            raise TypeError("jira_relation_profile expects JiraRelationProfile")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer expects TokenizerPort")
        if not callable(getattr(raw_page_mapper, "map_page", None)):
            raise TypeError("raw_page_mapper expects ConfluenceRawPageMapperPort")
        if not callable(getattr(storage_normalizer, "normalize", None)):
            raise TypeError(
                "storage_normalizer expects ConfluenceStorageNormalizerPort"
            )
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._chunking_profile = chunking_profile
        self._jira_relation_profile = jira_relation_profile
        self._tokenizer = tokenizer
        self._raw_page_mapper = raw_page_mapper
        self._storage_normalizer = storage_normalizer
        self._schema_validator = schema_validator

    def execute(
        self,
        *,
        page_id: str,
        raw_page_bytes: bytes,
        restriction_observations: object,
        crawled_at: str,
        relation_created_at: str,
        crawler_identity: str,
        acl_extracted_at: str,
    ) -> ConfluenceAclCompositionResult:
        # A public boundary must never leak a raw ValueError for an invalid
        # page identity; validate first so the private fixed-bytes reader
        # below never sees an unvalidated value.
        try:
            validated_page_id = require_confluence_page_id(page_id)
        except (TypeError, ValueError):
            raise ConfluencePageNormalizationError(
                CATEGORY_INVALID_PAGE_ID
            ) from None

        # Ownership-isolated deep copy taken before validation so two calls
        # with the same caller-owned observations validate independent copies
        # and never mutate or alias the caller's object (spec §11.2).
        observations_copy = deepcopy(restriction_observations)

        normalization = NormalizeConfluencePage(
            raw_page_reader=_FixedRawPageReader(
                expected_page_id=validated_page_id,
                raw_bytes=raw_page_bytes,
            ),
            raw_page_mapper=self._raw_page_mapper,
            storage_normalizer=self._storage_normalizer,
        ).execute(page_id=validated_page_id, crawled_at=crawled_at)
        structure = parse_wiki_document_structure(normalization)
        chunking_result = BuildConfluenceChunks(
            profile=self._chunking_profile,
            tokenizer=self._tokenizer,
            chunk_id_generator=ChunkIdGenerator,
            chunk_record_builder=ChunkRecordBuilder,
            schema_validator=self._schema_validator,
        ).execute(
            canonical_document=normalization.canonical_document,
            structure=structure,
        )
        jira_relation_result = BuildConfluenceJiraRelations(
            profile=self._jira_relation_profile,
            document_id_generator=DocumentIdGenerator,
            relation_id_generator=RelationIdGenerator,
            relation_record_builder=RelationRecordBuilder,
            schema_validator=self._schema_validator,
        ).execute(
            normalized_body_text=normalization.normalized_body_text,
            canonical_document=normalization.canonical_document,
            chunking_result=chunking_result,
            created_at=relation_created_at,
        )

        canonical_page_id = jira_relation_result.enriched_canonical_document.get(
            "page_id"
        )
        validated_observations = _bind_restriction_ancestry(
            observations_copy=observations_copy,
            canonical_page_id=canonical_page_id,
            raw_page_bytes=raw_page_bytes,
            selected_page_id=validated_page_id,
        )

        relation_before = deepcopy(jira_relation_result)
        observations_before = deepcopy(validated_observations)
        acl_result = MaterializeConfluenceAcl(
            schema_validator=self._schema_validator
        ).execute(
            jira_relation_result=jira_relation_result,
            restriction_observations=validated_observations,
            crawler_identity=crawler_identity,
            extracted_at=acl_extracted_at,
        )
        if (
            jira_relation_result != relation_before
            or validated_observations != observations_before
        ):
            raise ConfluenceAclCompositionAcceptanceError()

        self._verify_cross_binding(
            jira_relation_result=jira_relation_result,
            acl_result=acl_result,
        )

        return ConfluenceAclCompositionResult(
            jira_relation_result=jira_relation_result,
            acl_materialization_result=acl_result,
            validated_restriction_observations=validated_observations,
        )

    @staticmethod
    def _verify_cross_binding(
        *,
        jira_relation_result: ConfluenceJiraRelationResult,
        acl_result: ConfluenceAclMaterializationResult,
    ) -> None:
        if (
            acl_result.enriched_canonical_document
            != jira_relation_result.enriched_canonical_document
        ):
            raise ConfluenceAclCompositionAcceptanceError()
        if acl_result.relations != jira_relation_result.relations:
            raise ConfluenceAclCompositionAcceptanceError()
        if not _chunks_equal_except_acl(
            jira_relation_result.enriched_chunks, acl_result.enriched_chunks
        ):
            raise ConfluenceAclCompositionAcceptanceError()
        if (
            acl_result.jira_quality_observation
            != jira_relation_result.quality_observation
        ):
            raise ConfluenceAclCompositionAcceptanceError()
        if acl_result.jira_metrics != jira_relation_result.metrics:
            raise ConfluenceAclCompositionAcceptanceError()
