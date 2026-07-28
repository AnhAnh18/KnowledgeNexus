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

from knowledgenexus.foundation.application.use_cases.compose_confluence_acl import (
    ComposeConfluenceAcl,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    CATEGORY_INVALID_PAGE_ID,
    CATEGORY_RAW_PAGE_INPUT,
    ConfluencePageNormalizationError,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    ConfluenceAclCompositionAcceptanceError,
    ConfluenceAclCompositionResult,
    ConfluenceAclRestrictionAncestryError,
    ConfluenceChunkingError,
    ConfluenceJiraRelationError,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
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
    """A sanitized pre-materialization observation/ancestry failure.

    Kept as a distinct CLI-local marker (alongside the reusable
    ``ConfluenceAclRestrictionAncestryError`` the composition boundary raises
    in production) so tests can exercise ``main()``'s exit-code mapping in
    isolation from composition internals.
    """


class _AcceptanceError(Exception):
    """A sanitized post-composition invariant failure."""


class _AclMaterializationStageError(Exception):
    """Retain only the exact M6F-B category across the CLI boundary.

    Kept as a distinct CLI-local marker for the same reason as
    ``_RestrictionAncestryError``: production now lets the reusable
    ``AclMaterializationError`` propagate directly from ``ComposeConfluenceAcl``.
    """

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


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
    except (ConfluenceAclRestrictionAncestryError, _RestrictionAncestryError):
        return _fail(CATEGORY_RESTRICTION_ANCESTRY, EXIT_RESTRICTION_ANCESTRY)
    except AclMaterializationError as exc:
        return _fail(exc.category.value, EXIT_ACL_MATERIALIZATION)
    except _AclMaterializationStageError as exc:
        return _fail(exc.category, EXIT_ACL_MATERIALIZATION)
    except (ConfluenceAclCompositionAcceptanceError, _AcceptanceError):
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
    composer = ComposeConfluenceAcl(
        chunking_profile=chunking_profile,
        jira_relation_profile=jira_profile,
        tokenizer=tokenizer,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=validator,
    )

    first = composer.execute(
        page_id=args.page_id,
        raw_page_bytes=raw_bytes,
        restriction_observations=loaded_sidecar.restriction_observations,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
    )
    second = composer.execute(
        page_id=args.page_id,
        raw_page_bytes=raw_bytes,
        restriction_observations=loaded_sidecar.restriction_observations,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
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


def _accept(
    *,
    first: ConfluenceAclCompositionResult,
    second: ConfluenceAclCompositionResult,
    validator: FoundationSchemaValidator,
    evidence_kind: str,
) -> _RunOutcome:
    acl = first.acl_materialization_result
    trusted = first.jira_relation_result
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
