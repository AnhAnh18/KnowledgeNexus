"""Offline one-page Foundation full-snapshot export command (M6G-C)."""

from __future__ import annotations

import argparse
import json
import logging
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
from knowledgenexus.foundation.application.use_cases.project_one_page_export import (
    OnePageExportProjectionError,
    ProjectOnePageExport,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    ConfluenceAclCompositionAcceptanceError,
    ConfluenceAclCompositionResult,
    ConfluenceAclRestrictionAncestryError,
    ConfluenceChunkingError,
    ConfluenceJiraRelationError,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportConfigurationError,
)
from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    OnePageFullSnapshotExportResult,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParseError,
)
from knowledgenexus.foundation.infrastructure.config import (
    load_one_page_export_profile_bundle,
)
from knowledgenexus.foundation.infrastructure.exporters.one_page_full_snapshot_exporter import (
    OnePageFullSnapshotExporter,
    OnePageFullSnapshotExportError,
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
)

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_TOKENIZER = "tokenizer"
CATEGORY_STRUCTURE = "wiki_structure"
CATEGORY_RESTRICTION_SIDECAR = "restriction_sidecar"
CATEGORY_RESTRICTION_ANCESTRY = "restriction_ancestry"
CATEGORY_ACCEPTANCE = "acceptance"
CATEGORY_UNEXPECTED = "unexpected"
CATEGORY_EXPORT_CONFIGURATION = "export_configuration"
CATEGORY_EXPORT_PROJECTION = "export_projection"
CATEGORY_EXPORT_ACCEPTANCE = "export_acceptance"

EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_NORMALIZATION = 3
EXIT_STRUCTURE = 4
# 5 (chunking_profile) is reserved by the shared taxonomy but structurally
# unreachable from this CLI: load_one_page_export_profile_bundle validates
# both profiles as one atomic operation (R3).
EXIT_TOKENIZER = 6
EXIT_CHUNKING = 7
# 8 (invalid_jira_relation_profile) is reserved but unreachable, same reason.
EXIT_RELATION = 9
EXIT_RESTRICTION_SIDECAR = 10
EXIT_RESTRICTION_ANCESTRY = 11
EXIT_ACL_MATERIALIZATION = 12
EXIT_ACCEPTANCE = 13
EXIT_EXPORT_CONFIGURATION = 14
EXIT_EXPORT_PROJECTION = 15
EXIT_EXPORT_STAGING = 16
EXIT_EXPORT_COMPLETION = 17
EXIT_EXPORT_PUBLICATION = 18
EXIT_EXPORT_ACCEPTANCE = 19

_EXPORT_ERROR_EXIT_CODES: dict[str, int] = {
    "export_projection": EXIT_EXPORT_PROJECTION,
    "export_staging": EXIT_EXPORT_STAGING,
    "export_completion": EXIT_EXPORT_COMPLETION,
    "export_publication": EXIT_EXPORT_PUBLICATION,
    "export_acceptance": EXIT_EXPORT_ACCEPTANCE,
}

# The M3 writer/completer/publisher log cleanup failures via
# logger.warning(..., exc_info=True), which embeds the filesystem path and a
# traceback. None of those modules configures a handler, so Python's logging
# "handler of last resort" would otherwise print them straight to stderr,
# bypassing this CLI's sanitized-output contract (spec §10) even though the
# CLI's own exception handling never leaks anything. Silence them by name.
_LEAKY_M3_LOGGER_NAMES = (
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer",
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer",
    "knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher",
)


def _silence_leaky_m3_loggers() -> None:
    for name in _LEAKY_M3_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


class _ConfigurationError(Exception):
    """A sanitized CLI configuration failure."""


class _AcceptanceError(Exception):
    """A sanitized pre-export composition/projection acceptance failure."""


class _PreExportSourceMutationError(Exception):
    """Raw page or sidecar mutated before any M3 output was written (R5)."""


class _PostPublicationSourceMutationError(Exception):
    """Raw page or sidecar mutated after publication was completed (R5)."""


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
    projection_deterministic: bool
    raw_page_unchanged: bool
    sidecar_unchanged: bool
    manifest_schema_valid: bool
    manifest_counts_match: bool
    records_match_projection: bool
    deferred_streams_empty: bool
    final_file_set_valid: bool
    quality_report_unchanged: bool
    latest_pointer_valid: bool


def main(argv: Sequence[str] | None = None) -> int:
    _silence_leaky_m3_loggers()
    try:
        args = _parse_args(argv)
        outcome = _run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION, EXIT_CONFIGURATION)
    except OnePageExportConfigurationError as exc:
        return _fail_export_configuration(exc)
    except ConfluencePageNormalizationError as exc:
        return _fail(exc.category, EXIT_NORMALIZATION)
    except WikiStructureParseError as exc:
        return _fail(CATEGORY_STRUCTURE, EXIT_STRUCTURE, detail=exc.category)
    except TokenizerError as exc:
        return _fail(CATEGORY_TOKENIZER, EXIT_TOKENIZER, detail=exc.category.value)
    except ConfluenceChunkingError as exc:
        return _fail(exc.category.value, EXIT_CHUNKING)
    except ConfluenceJiraRelationError as exc:
        return _fail(exc.category.value, EXIT_RELATION)
    except RestrictionSidecarLoadError:
        return _fail(CATEGORY_RESTRICTION_SIDECAR, EXIT_RESTRICTION_SIDECAR)
    except ConfluenceAclRestrictionAncestryError:
        return _fail(CATEGORY_RESTRICTION_ANCESTRY, EXIT_RESTRICTION_ANCESTRY)
    except AclMaterializationError as exc:
        return _fail(exc.category.value, EXIT_ACL_MATERIALIZATION)
    except ConfluenceAclCompositionAcceptanceError:
        return _fail(CATEGORY_ACCEPTANCE, EXIT_ACCEPTANCE)
    except _AcceptanceError:
        return _fail(CATEGORY_ACCEPTANCE, EXIT_ACCEPTANCE)
    except _PreExportSourceMutationError:
        return _fail(CATEGORY_ACCEPTANCE, EXIT_ACCEPTANCE)
    except OnePageExportProjectionError:
        return _fail(CATEGORY_EXPORT_PROJECTION, EXIT_EXPORT_PROJECTION)
    except OnePageFullSnapshotExportError as exc:
        return _fail(exc.category, _EXPORT_ERROR_EXIT_CODES[exc.category])
    except _PostPublicationSourceMutationError:
        return _fail(CATEGORY_EXPORT_ACCEPTANCE, EXIT_EXPORT_ACCEPTANCE)
    except BaseException:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED)

    summary = {
        "status": "success",
        "restriction_evidence_kind": outcome.evidence_kind,
        "real_captured_evidence": (
            outcome.evidence_kind == CAPTURED_M6B_EVIDENCE_KIND
        ),
        "network_used": False,
        "credentials_used": False,
        "restriction_ancestry_bound": outcome.restriction_ancestry_bound,
        "acl_record_schema_valid": outcome.acl_record_schema_valid,
        "chunks_schema_valid": outcome.chunks_schema_valid,
        "canonical_unchanged": outcome.canonical_unchanged,
        "relations_unchanged": outcome.relations_unchanged,
        "chunk_non_acl_fields_unchanged": outcome.chunk_non_acl_fields_unchanged,
        "chunk_acl_tags_match_acl_record": outcome.chunk_acl_tags_match_acl_record,
        "deterministic_repeat": outcome.deterministic_repeat,
        "projection_deterministic": outcome.projection_deterministic,
        "raw_page_unchanged": outcome.raw_page_unchanged,
        "sidecar_unchanged": outcome.sidecar_unchanged,
        "output_files_created": True,
        "manifest_schema_valid": outcome.manifest_schema_valid,
        "manifest_counts_match": outcome.manifest_counts_match,
        "records_match_projection": outcome.records_match_projection,
        "deferred_streams_empty": outcome.deferred_streams_empty,
        "final_file_set_valid": outcome.final_file_set_valid,
        "quality_report_complete": True,
        "quality_report_unchanged": outcome.quality_report_unchanged,
        "latest_pointer_valid": outcome.latest_pointer_valid,
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
        export_root = Path(args.export_root)
    except (TypeError, ValueError):
        raise _ConfigurationError from None

    raw_store = ConfluencePageObservationStore(raw_root=raw_root)
    raw_bytes = _read_raw_page(raw_store=raw_store, page_id=args.page_id)
    loaded_sidecar, sidecar_bytes = load_restriction_sidecar(sidecar_path)
    loaded_before = deepcopy(loaded_sidecar)

    bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=profile_path,
        jira_relation_profile_path=jira_profile_path,
    )
    tokenizer = BgeM3LocalTokenizer(
        profile=bundle.chunking_profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()
    composer = ComposeConfluenceAcl(
        chunking_profile=bundle.chunking_profile,
        jira_relation_profile=bundle.jira_relation_profile,
        tokenizer=tokenizer,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=validator,
    )
    projector = ProjectOnePageExport(schema_validator=validator)

    composed_first = composer.execute(
        page_id=args.page_id,
        raw_page_bytes=raw_bytes,
        restriction_observations=loaded_sidecar.restriction_observations,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
    )
    composed_second = composer.execute(
        page_id=args.page_id,
        raw_page_bytes=raw_bytes,
        restriction_observations=loaded_sidecar.restriction_observations,
        crawled_at=args.crawled_at,
        relation_created_at=args.relation_created_at,
        crawler_identity=args.crawler_identity,
        acl_extracted_at=args.acl_extracted_at,
    )
    if composed_first != composed_second:
        raise _AcceptanceError

    projection_first = projector.execute(
        acl_result=composed_first.acl_materialization_result,
        profile_bundle=bundle,
    )
    projection_second = projector.execute(
        acl_result=composed_second.acl_materialization_result,
        profile_bundle=bundle,
    )
    projection_deterministic = projection_first == projection_second
    if not projection_deterministic:
        raise _AcceptanceError

    try:
        raw_before_export = _read_raw_page(raw_store=raw_store, page_id=args.page_id)
    except ConfluencePageNormalizationError:
        raise _PreExportSourceMutationError from None
    if raw_before_export != raw_bytes:
        raise _PreExportSourceMutationError
    try:
        sidecar_before_export, sidecar_bytes_before_export = load_restriction_sidecar(
            sidecar_path
        )
    except RestrictionSidecarLoadError:
        raise _PreExportSourceMutationError from None
    if (
        sidecar_bytes_before_export != sidecar_bytes
        or sidecar_before_export != loaded_before
    ):
        raise _PreExportSourceMutationError

    export_result = OnePageFullSnapshotExporter.export(
        projection=projection_first,
        generated_at=args.generated_at,
        export_root=export_root,
        validator=validator,
    )

    try:
        raw_after_export = _read_raw_page(raw_store=raw_store, page_id=args.page_id)
    except ConfluencePageNormalizationError:
        raise _PostPublicationSourceMutationError from None
    if raw_after_export != raw_bytes:
        raise _PostPublicationSourceMutationError
    try:
        sidecar_after_export, sidecar_bytes_after_export = load_restriction_sidecar(
            sidecar_path
        )
    except RestrictionSidecarLoadError:
        raise _PostPublicationSourceMutationError from None
    if (
        sidecar_bytes_after_export != sidecar_bytes
        or sidecar_after_export != loaded_before
    ):
        raise _PostPublicationSourceMutationError

    return _accept(
        composed_first=composed_first,
        composed_second=composed_second,
        projection_deterministic=projection_deterministic,
        export_result=export_result,
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
    composed_first: ConfluenceAclCompositionResult,
    composed_second: ConfluenceAclCompositionResult,
    projection_deterministic: bool,
    export_result: OnePageFullSnapshotExportResult,
    evidence_kind: str,
) -> _RunOutcome:
    acl = composed_first.acl_materialization_result
    trusted = composed_first.jira_relation_result
    canonical_unchanged = (
        acl.enriched_canonical_document == trusted.enriched_canonical_document
    )
    relations_unchanged = acl.relations == trusted.relations
    chunk_non_acl_fields_unchanged = _chunks_equal_except_acl(
        trusted.enriched_chunks, acl.enriched_chunks
    )
    acl_tags = acl.acl_record.get("acl_tags")
    chunk_acl_tags_match = (
        isinstance(acl_tags, list)
        and bool(acl_tags)
        and all(chunk.get("acl_tags") == acl_tags for chunk in acl.enriched_chunks)
    )
    deterministic_repeat = composed_first == composed_second

    if (
        not canonical_unchanged
        or not relations_unchanged
        or not chunk_non_acl_fields_unchanged
        or not chunk_acl_tags_match
        or not deterministic_repeat
    ):
        raise _AcceptanceError

    acceptance = export_result.acceptance
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
        projection_deterministic=projection_deterministic,
        raw_page_unchanged=True,
        sidecar_unchanged=True,
        manifest_schema_valid=acceptance.manifest_schema_valid,
        manifest_counts_match=acceptance.manifest_counts_match,
        records_match_projection=acceptance.records_match_projection,
        deferred_streams_empty=acceptance.deferred_streams_empty,
        final_file_set_valid=acceptance.final_file_set_valid,
        quality_report_unchanged=acceptance.quality_report_unchanged_after_publication,
        latest_pointer_valid=acceptance.latest_pointer_valid,
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


def _fail(
    category: str,
    exit_code: int,
    *,
    detail: str | None = None,
) -> int:
    payload: dict[str, object] = {"status": "failed", "category": category}
    if detail is not None:
        payload["detail"] = detail
    sys.stderr.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    )
    return exit_code


def _fail_export_configuration(error: OnePageExportConfigurationError) -> int:
    """Project only typed, closed-vocabulary configuration diagnostics."""

    payload = {
        "status": "failed",
        "category": CATEGORY_EXPORT_CONFIGURATION,
        "stage": error.stage.value,
        "cause_family": error.cause_family.value,
    }
    sys.stderr.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    )
    return EXIT_EXPORT_CONFIGURATION


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """Never echo identities, principals, paths, or profile values."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="export-confluence-one-page-snapshot",
        description=(
            "Export one preserved Confluence page as a full-snapshot Foundation "
            "dataset offline, through the existing M3 writer/completer/publisher."
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
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--export-root", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
