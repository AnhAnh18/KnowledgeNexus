"""Offline one-page M6F composition and ACL acceptance command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

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
    CATEGORY_RAW_PAGE_INPUT,
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    ConfluenceAclMaterializationResult,
    ConfluenceChunkingError,
    ConfluenceJiraRelationError,
    ConfluenceJiraRelationResult,
)
from knowledgenexus.foundation.domain.records import (
    ChunkRecordBuilder,
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import (
    ChunkIdGenerator,
    DocumentIdGenerator,
    RelationIdGenerator,
)
from knowledgenexus.foundation.domain.rules.acl_restriction_observations import (
    validate_restriction_observations,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_observations import (
    ConfluencePageObservationPayloadError,
    extract_ordered_restriction_targets,
)
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParseError,
)
from knowledgenexus.foundation.infrastructure.config import (
    ChunkingProfileLoadError,
    JiraRelationProfileLoadError,
    load_chunking_profile,
    load_jira_relation_profile,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    CAPTURED_M6B_EVIDENCE_KIND,
    LoadedRestrictionSidecar,
    RestrictionSidecarLoadError,
    load_restriction_sidecar,
)
from knowledgenexus.foundation.infrastructure.tokenization import (
    BgeM3LocalTokenizer,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
    RawPageReadPort,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerError
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_CHUNKING_PROFILE = "chunking_profile"
CATEGORY_JIRA_PROFILE = "invalid_jira_relation_profile"
CATEGORY_TOKENIZER = "tokenizer"
CATEGORY_STRUCTURE = "wiki_structure"
CATEGORY_RESTRICTION_SIDECAR = "restriction_sidecar"
CATEGORY_RESTRICTION_ANCESTRY = "restriction_ancestry"
CATEGORY_ACCEPTANCE = "acceptance"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_NORMALIZATION = 3
EXIT_STRUCTURE = 4
EXIT_CHUNKING_PROFILE = 5
EXIT_TOKENIZER = 6
EXIT_CHUNKING = 7
EXIT_JIRA_PROFILE = 8
EXIT_RELATION = 9
EXIT_RESTRICTION_SIDECAR = 10
EXIT_RESTRICTION_ANCESTRY = 11
EXIT_ACL_MATERIALIZATION = 12
EXIT_ACCEPTANCE = 13


class _ConfigurationError(Exception):
    """A sanitized CLI configuration failure."""


class _RestrictionAncestryError(Exception):
    """A sanitized pre-materialization observation/ancestry failure."""


class _AcceptanceError(Exception):
    """A sanitized post-composition invariant failure."""


class _AclMaterializationStageError(Exception):
    """Retain only the exact M6F-B category across the CLI boundary."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, repr=False)
class _FixedRawPageReader(RawPageReadPort):
    expected_page_id: str
    raw_bytes: bytes

    def __post_init__(self) -> None:
        try:
            page_id = require_confluence_page_id(self.expected_page_id)
        except (TypeError, ValueError):
            raise ValueError("expected page identity is invalid") from None
        if not isinstance(self.raw_bytes, bytes):
            raise TypeError("raw_bytes expects bytes")
        object.__setattr__(self, "expected_page_id", page_id)
        object.__setattr__(self, "raw_bytes", bytes(self.raw_bytes))

    def read_page(self, *, page_id: str) -> bytes:
        try:
            observed = require_confluence_page_id(page_id)
        except (TypeError, ValueError):
            raise RawPageReadError("raw page identity is invalid") from None
        if observed != self.expected_page_id:
            raise RawPageReadError("raw page identity does not match")
        return self.raw_bytes


@dataclass(frozen=True, repr=False)
class _Composition:
    relation_result: ConfluenceJiraRelationResult
    acl_result: ConfluenceAclMaterializationResult
    validated_observations: tuple[dict[str, object], ...]


@dataclass(frozen=True, repr=False)
class _RunOutcome:
    evidence_kind: str
    restriction_ancestry_bound: bool
    acl_record_schema_valid: bool
    chunks_schema_valid: bool
    canonical_unchanged: bool
    relations_unchanged: bool
    chunk_non_acl_fields_unchanged: bool
    chunk_acl_tags_match_acl_record: bool
    deterministic_repeat: bool
    raw_page_unchanged: bool
    sidecar_unchanged: bool


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        outcome = _run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION, EXIT_CONFIGURATION)
    except ConfluencePageNormalizationError as exc:
        return _fail(exc.category, EXIT_NORMALIZATION)
    except WikiStructureParseError as exc:
        return _fail(CATEGORY_STRUCTURE, EXIT_STRUCTURE, detail=exc.category)
    except ChunkingProfileLoadError:
        return _fail(CATEGORY_CHUNKING_PROFILE, EXIT_CHUNKING_PROFILE)
    except JiraRelationProfileLoadError:
        return _fail(CATEGORY_JIRA_PROFILE, EXIT_JIRA_PROFILE)
    except TokenizerError as exc:
        return _fail(CATEGORY_TOKENIZER, EXIT_TOKENIZER, detail=exc.category.value)
    except ConfluenceChunkingError as exc:
        return _fail(exc.category.value, EXIT_CHUNKING)
    except ConfluenceJiraRelationError as exc:
        return _fail(exc.category.value, EXIT_RELATION)
    except RestrictionSidecarLoadError:
        return _fail(CATEGORY_RESTRICTION_SIDECAR, EXIT_RESTRICTION_SIDECAR)
    except _RestrictionAncestryError:
        return _fail(CATEGORY_RESTRICTION_ANCESTRY, EXIT_RESTRICTION_ANCESTRY)
    except _AclMaterializationStageError as exc:
        return _fail(exc.category, EXIT_ACL_MATERIALIZATION)
    except _AcceptanceError:
        return _fail(CATEGORY_ACCEPTANCE, EXIT_ACCEPTANCE)
    except BaseException:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED)

    summary = {
        "status": "success",
        "restriction_evidence_kind": outcome.evidence_kind,
        "real_captured_evidence": (
            outcome.evidence_kind == CAPTURED_M6B_EVIDENCE_KIND
        ),
        "restriction_ancestry_bound": outcome.restriction_ancestry_bound,
        "acl_record_schema_valid": outcome.acl_record_schema_valid,
        "chunks_schema_valid": outcome.chunks_schema_valid,
        "canonical_unchanged": outcome.canonical_unchanged,
        "relations_unchanged": outcome.relations_unchanged,
        "chunk_non_acl_fields_unchanged": (
            outcome.chunk_non_acl_fields_unchanged
        ),
        "chunk_acl_tags_match_acl_record": (
            outcome.chunk_acl_tags_match_acl_record
        ),
        "deterministic_repeat": outcome.deterministic_repeat,
        "raw_page_unchanged": outcome.raw_page_unchanged,
        "sidecar_unchanged": outcome.sidecar_unchanged,
        "network_used": False,
        "output_files_created": False,
    }
    sys.stdout.write(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    )
    return 0


def _run(args: argparse.Namespace) -> _RunOutcome:
    try:
        raw_root = Path(args.raw_root)
        profile_path = Path(args.profile_path)
        tokenizer_assets_dir = Path(args.tokenizer_assets_dir)
        jira_profile_path = Path(args.jira_profile_path)
        sidecar_path = Path(args.restriction_sidecar_path)
    except (TypeError, ValueError):
        raise _ConfigurationError from None

    raw_store = ConfluencePageObservationStore(raw_root=raw_root)
    raw_bytes = _read_raw_page(
        raw_store=raw_store,
        page_id=args.page_id,
    )
    loaded_sidecar, sidecar_bytes = load_restriction_sidecar(sidecar_path)
    loaded_before = deepcopy(loaded_sidecar)

    chunking_profile = load_chunking_profile(profile_path)
    jira_profile = load_jira_relation_profile(jira_profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=chunking_profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()

    first = _compose_once(
        page_id=args.page_id,
        raw_bytes=raw_bytes,
        loaded_sidecar=loaded_sidecar,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
        chunking_profile=chunking_profile,
        jira_profile=jira_profile,
        tokenizer=tokenizer,
        validator=validator,
    )
    second = _compose_once(
        page_id=args.page_id,
        raw_bytes=raw_bytes,
        loaded_sidecar=loaded_sidecar,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
        chunking_profile=chunking_profile,
        jira_profile=jira_profile,
        tokenizer=tokenizer,
        validator=validator,
    )

    raw_after = _read_raw_page(raw_store=raw_store, page_id=args.page_id)
    if raw_after != raw_bytes:
        raise _AcceptanceError
    try:
        sidecar_after, sidecar_bytes_after = load_restriction_sidecar(
            sidecar_path
        )
    except RestrictionSidecarLoadError:
        raise _AcceptanceError from None
    if sidecar_bytes_after != sidecar_bytes or sidecar_after != loaded_before:
        raise _AcceptanceError
    if loaded_sidecar != loaded_before:
        raise _AcceptanceError

    return _accept(
        first=first,
        second=second,
        validator=validator,
        evidence_kind=loaded_sidecar.evidence_kind,
    )


def _read_raw_page(
    *,
    raw_store: ConfluencePageObservationStore,
    page_id: str,
) -> bytes:
    try:
        page_id = require_confluence_page_id(page_id)
    except (TypeError, ValueError):
        raise ConfluencePageNormalizationError(CATEGORY_INVALID_PAGE_ID) from None
    try:
        return raw_store.read_page(page_id=page_id)
    except (RawPageReadError, OSError, TypeError, ValueError):
        raise ConfluencePageNormalizationError(CATEGORY_RAW_PAGE_INPUT) from None


def _compose_once(
    *,
    page_id: str,
    raw_bytes: bytes,
    loaded_sidecar: LoadedRestrictionSidecar,
    crawled_at: str,
    relation_created_at: str,
    crawler_identity: str,
    acl_extracted_at: str,
    chunking_profile: object,
    jira_profile: object,
    tokenizer: object,
    validator: FoundationSchemaValidator,
) -> _Composition:
    normalization = NormalizeConfluencePage(
        raw_page_reader=_FixedRawPageReader(
            expected_page_id=page_id,
            raw_bytes=raw_bytes,
        ),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    ).execute(page_id=page_id, crawled_at=crawled_at)
    structure = parse_wiki_document_structure(normalization)
    chunks = BuildConfluenceChunks(
        profile=chunking_profile,  # type: ignore[arg-type]
        tokenizer=tokenizer,  # type: ignore[arg-type]
        chunk_id_generator=ChunkIdGenerator,
        chunk_record_builder=ChunkRecordBuilder,
        schema_validator=validator,
    ).execute(
        canonical_document=normalization.canonical_document,
        structure=structure,
    )
    relation_result = BuildConfluenceJiraRelations(
        profile=jira_profile,  # type: ignore[arg-type]
        document_id_generator=DocumentIdGenerator,
        relation_id_generator=RelationIdGenerator,
        relation_record_builder=RelationRecordBuilder,
        schema_validator=validator,
    ).execute(
        normalized_body_text=normalization.normalized_body_text,
        canonical_document=normalization.canonical_document,
        chunking_result=chunks,
        created_at=relation_created_at,
    )

    canonical_page_id = relation_result.enriched_canonical_document.get("page_id")
    validated = _bind_restriction_ancestry(
        loaded_sidecar=loaded_sidecar,
        canonical_page_id=canonical_page_id,
        raw_bytes=raw_bytes,
        selected_page_id=page_id,
    )

    relation_before = deepcopy(relation_result)
    observations_before = deepcopy(validated)
    try:
        acl_result = MaterializeConfluenceAcl(
            schema_validator=validator
        ).execute(
            jira_relation_result=relation_result,
            restriction_observations=validated,
            crawler_identity=crawler_identity,
            extracted_at=acl_extracted_at,
        )
    except AclMaterializationError as exc:
        raise _AclMaterializationStageError(exc.category.value) from None
    if relation_result != relation_before or validated != observations_before:
        raise _AcceptanceError

    return _Composition(
        relation_result=relation_result,
        acl_result=acl_result,
        validated_observations=validated,
    )


def _bind_restriction_ancestry(
    *,
    loaded_sidecar: LoadedRestrictionSidecar,
    canonical_page_id: object,
    raw_bytes: bytes,
    selected_page_id: str,
) -> tuple[dict[str, object], ...]:
    try:
        observations_input = deepcopy(loaded_sidecar.restriction_observations)
        validated = validate_restriction_observations(
            observations_input,
            canonical_page_id=canonical_page_id,
        )
        expected_targets = extract_ordered_restriction_targets(
            raw_page=raw_bytes,
            selected_page_id=selected_page_id,
        )
    except (
        AclMaterializationError,
        ConfluencePageObservationPayloadError,
        TypeError,
        ValueError,
    ):
        raise _RestrictionAncestryError from None

    observed_targets = tuple(
        str(observation["source_page_id"]) for observation in validated
    )
    if observed_targets != expected_targets:
        raise _RestrictionAncestryError
    return validated


def _accept(
    *,
    first: _Composition,
    second: _Composition,
    validator: FoundationSchemaValidator,
    evidence_kind: str,
) -> _RunOutcome:
    acl = first.acl_result
    trusted = first.relation_result
    try:
        validator.validate_record("ACLRecord", acl.acl_record)
        for chunk in acl.enriched_chunks:
            validator.validate_record("ChunkRecord", chunk)
    except (FoundationValidationError, TypeError, ValueError):
        raise _AcceptanceError from None

    acl_records_total = acl.metrics.get("acl_records_total")
    canonical_unchanged = (
        acl.enriched_canonical_document
        == trusted.enriched_canonical_document
    )
    relations_unchanged = acl.relations == trusted.relations
    chunk_non_acl_fields_unchanged = _chunks_equal_except_acl(
        trusted.enriched_chunks,
        acl.enriched_chunks,
    )
    acl_tags = acl.acl_record.get("acl_tags")
    chunk_acl_tags_match = (
        isinstance(acl_tags, list)
        and bool(acl_tags)
        and all(chunk.get("acl_tags") == acl_tags for chunk in acl.enriched_chunks)
    )
    deterministic_repeat = first == second

    if (
        isinstance(acl_records_total, bool)
        or acl_records_total != 1
        or not canonical_unchanged
        or not relations_unchanged
        or not chunk_non_acl_fields_unchanged
        or not chunk_acl_tags_match
        or not deterministic_repeat
    ):
        raise _AcceptanceError

    return _RunOutcome(
        evidence_kind=evidence_kind,
        restriction_ancestry_bound=True,
        acl_record_schema_valid=True,
        chunks_schema_valid=True,
        canonical_unchanged=canonical_unchanged,
        relations_unchanged=relations_unchanged,
        chunk_non_acl_fields_unchanged=chunk_non_acl_fields_unchanged,
        chunk_acl_tags_match_acl_record=chunk_acl_tags_match,
        deterministic_repeat=deterministic_repeat,
        raw_page_unchanged=True,
        sidecar_unchanged=True,
    )


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


def _fail(category: str, exit_code: int, *, detail: str | None = None) -> int:
    payload = {"status": "failed", "category": category}
    if detail is not None:
        payload["detail"] = detail
    sys.stderr.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    )
    return exit_code


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """Never echo identities, principals, paths, or profile values."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="materialize-confluence-acl",
        description=(
            "Compose and validate one preserved Confluence page ACL offline "
            "without writing records."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    parser.add_argument("--jira-profile-path", required=True)
    parser.add_argument("--crawled-at", required=True)
    parser.add_argument("--relation-created-at", required=True)
    parser.add_argument("--restriction-sidecar-path", required=True)
    parser.add_argument("--crawler-identity", required=True)
    parser.add_argument("--acl-extracted-at", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
