"""Offline M6A -> M6C -> M6D-C -> M6D-D one-page acceptance command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.build_confluence_chunks import (
    BuildConfluenceChunks,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models.confluence_chunking import (
    ChunkingResult,
    ConfluenceChunkingError,
)
from knowledgenexus.foundation.domain.records.chunk_record_builder import (
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParseError,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    ChunkingProfileLoadError,
    load_chunking_profile,
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
CATEGORY_PROFILE = "chunking_profile"
CATEGORY_TOKENIZER = "tokenizer"
CATEGORY_STRUCTURE = "wiki_structure"
CATEGORY_ACCEPTANCE = "acceptance_invariant"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_NORMALIZATION = 3
EXIT_STRUCTURE = 4
EXIT_PROFILE = 5
EXIT_TOKENIZER = 6
EXIT_CHUNKING = 7


class _ConfigurationError(Exception):
    """A sanitized CLI configuration failure."""


@dataclass(frozen=True, repr=False)
class _RunOutcome:
    result: ChunkingResult
    deterministic_repeat: bool
    active_profile: str
    chunker_version: str


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
        return _fail(CATEGORY_PROFILE, EXIT_PROFILE)
    except TokenizerError as exc:
        return _fail(CATEGORY_TOKENIZER, EXIT_TOKENIZER, detail=exc.category.value)
    except ConfluenceChunkingError as exc:
        return _fail(exc.category.value, EXIT_CHUNKING)
    except BaseException:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED)

    records = outcome.result.records
    chunks_over = _metric_int(outcome.result.metrics, "chunks_over_hard_max")
    maximum_tokens = _metric_int(outcome.result.metrics, "maximum_token_count")
    all_acl_default_deny = all(
        record.get("acl_tags") == ["restricted:unresolved"]
        for record in records
    )
    if (
        not outcome.deterministic_repeat
        or chunks_over != 0
        or not all_acl_default_deny
    ):
        return _fail(CATEGORY_ACCEPTANCE, EXIT_CHUNKING)
    summary = {
        "status": "success",
        "profile": outcome.active_profile,
        "chunker_version": outcome.chunker_version,
        "chunk_count": len(records),
        "schema_valid": True,
        "maximum_token_count": maximum_tokens,
        "chunks_over_hard_max": chunks_over,
        "all_acl_tags_default_deny": all_acl_default_deny,
        "deterministic_repeat": outcome.deterministic_repeat,
        "network_used": False,
        "output_files_created": False,
    }
    sys.stdout.write(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    return 0


def _run(args: argparse.Namespace) -> _RunOutcome:
    try:
        raw_root = Path(args.raw_root)
        profile_path = Path(args.profile_path)
        tokenizer_assets_dir = Path(args.tokenizer_assets_dir)
    except (TypeError, ValueError) as exc:
        raise _ConfigurationError from exc

    profile = load_chunking_profile(profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    schema_validator = FoundationSchemaValidator()
    normalization = NormalizeConfluencePage(
        raw_page_reader=ConfluencePageObservationStore(raw_root=raw_root),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    ).execute(page_id=args.page_id, crawled_at=args.crawled_at)
    structure = parse_wiki_document_structure(normalization)
    use_case = BuildConfluenceChunks(
        profile=profile,
        tokenizer=tokenizer,
        chunk_id_generator=ChunkIdGenerator,
        chunk_record_builder=ChunkRecordBuilder,
        schema_validator=schema_validator,
    )
    first = use_case.execute(
        canonical_document=normalization.canonical_document,
        structure=structure,
    )
    second = use_case.execute(
        canonical_document=normalization.canonical_document,
        structure=structure,
    )
    return _RunOutcome(
        result=first,
        deterministic_repeat=(
            first.records == second.records and first.metrics == second.metrics
        ),
        active_profile=profile.active_profile,
        chunker_version=profile.chunker_version,
    )


def _metric_int(metrics: dict[str, object], name: str) -> int:
    value = metrics.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _fail(category: str, exit_code: int, *, detail: str | None = None) -> int:
    payload = {"status": "failed", "category": category}
    if detail is not None:
        payload["detail"] = detail
    sys.stderr.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    return exit_code


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """Never echo page identity or operator filesystem paths."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="build-confluence-chunks",
        description=(
            "Build and validate deterministic one-page Confluence chunks "
            "offline without writing them."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    parser.add_argument("--crawled-at", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
