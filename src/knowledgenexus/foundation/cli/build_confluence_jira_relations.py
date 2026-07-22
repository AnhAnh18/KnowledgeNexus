"""Offline M6A -> M6C -> M6D -> M6E one-page acceptance command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases import (
    BuildConfluenceChunks,
    BuildConfluenceJiraRelations,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
)
from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models import (
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
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerError
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


CATEGORY_CONFIGURATION = "configuration"
CATEGORY_CHUNKING_PROFILE = "chunking_profile"
CATEGORY_JIRA_PROFILE = "invalid_jira_relation_profile"
CATEGORY_TOKENIZER = "tokenizer"
CATEGORY_STRUCTURE = "wiki_structure"
CATEGORY_ACCEPTANCE = "acceptance_invariant"
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


class _ConfigurationError(Exception):
    """A sanitized CLI configuration failure."""


@dataclass(frozen=True, repr=False)
class _RunOutcome:
    result: ConfluenceJiraRelationResult
    deterministic_repeat: bool
    chunk_identity_content_unchanged: bool
    acl_unchanged: bool


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
    except Exception:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED)

    metrics = outcome.result.metrics
    relation_count = _metric_int(metrics, "relations_total")
    zero_relations_valid = relation_count != 0 or (
        outcome.result.relations == ()
        and outcome.result.enriched_canonical_document.get("jira_keys") == []
        and outcome.result.enriched_canonical_document.get("relation_ids") == []
        and all(
            chunk.get("jira_keys") == [] and chunk.get("relation_ids") == []
            for chunk in outcome.result.enriched_chunks
        )
    )
    if (
        not outcome.deterministic_repeat
        or not outcome.chunk_identity_content_unchanged
        or not outcome.acl_unchanged
        or not zero_relations_valid
    ):
        return _fail(CATEGORY_ACCEPTANCE, EXIT_RELATION)

    summary = {
        "status": "success",
        "relation_type": "mentions_jira_key",
        "candidate_count": _metric_int(metrics, "candidate_occurrences"),
        "allowlisted_count": _metric_int(metrics, "allowlisted_unique_count"),
        "outside_allowlist_count": _metric_int(
            metrics, "outside_allowlist_unique_count"
        ),
        "relation_count": relation_count,
        "zero_relations_valid": zero_relations_valid,
        "schema_valid": True,
        "chunk_identity_content_unchanged": (
            outcome.chunk_identity_content_unchanged
        ),
        "acl_unchanged": outcome.acl_unchanged,
        "deterministic_repeat": outcome.deterministic_repeat,
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
    except (TypeError, ValueError) as exc:
        raise _ConfigurationError from exc

    chunking_profile = load_chunking_profile(profile_path)
    jira_profile = load_jira_relation_profile(jira_profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=chunking_profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()
    normalization = NormalizeConfluencePage(
        raw_page_reader=ConfluencePageObservationStore(raw_root=raw_root),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    ).execute(page_id=args.page_id, crawled_at=args.crawled_at)
    structure = parse_wiki_document_structure(normalization)
    chunks = BuildConfluenceChunks(
        profile=chunking_profile,
        tokenizer=tokenizer,
        chunk_id_generator=ChunkIdGenerator,
        chunk_record_builder=ChunkRecordBuilder,
        schema_validator=validator,
    ).execute(
        canonical_document=normalization.canonical_document,
        structure=structure,
    )
    relation_use_case = BuildConfluenceJiraRelations(
        profile=jira_profile,
        document_id_generator=DocumentIdGenerator,
        relation_id_generator=RelationIdGenerator,
        relation_record_builder=RelationRecordBuilder,
        schema_validator=validator,
    )
    first = relation_use_case.execute(
        normalized_body_text=normalization.normalized_body_text,
        canonical_document=normalization.canonical_document,
        chunking_result=chunks,
        created_at=args.relation_created_at,
    )
    second = relation_use_case.execute(
        normalized_body_text=normalization.normalized_body_text,
        canonical_document=normalization.canonical_document,
        chunking_result=chunks,
        created_at=args.relation_created_at,
    )
    return _RunOutcome(
        result=first,
        deterministic_repeat=(first == second),
        chunk_identity_content_unchanged=_chunks_unchanged_except_links(
            chunks.records, first.enriched_chunks
        ),
        acl_unchanged=all(
            original.get("acl_tags") == enriched.get("acl_tags")
            for original, enriched in zip(
                chunks.records, first.enriched_chunks, strict=True
            )
        ),
    )


def _chunks_unchanged_except_links(
    original: tuple[dict[str, object], ...],
    enriched: tuple[dict[str, object], ...],
) -> bool:
    if len(original) != len(enriched):
        return False
    for before, after in zip(original, enriched, strict=True):
        stripped = dict(after)
        stripped["jira_keys"] = []
        stripped["relation_ids"] = []
        if stripped != before:
            return False
    return True


def _metric_int(metrics: dict[str, object], name: str) -> int:
    value = metrics.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


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
    """Never echo page identity, filesystem paths, or Jira configuration."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="build-confluence-jira-relations",
        description=(
            "Build and validate deterministic page-level Jira relations "
            "offline without writing them."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    parser.add_argument("--jira-profile-path", required=True)
    parser.add_argument("--crawled-at", required=True)
    parser.add_argument("--relation-created-at", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
