"""Offline operator entrypoint for one preserved Confluence page.

The command reads only the deterministic M6A raw-page path, normalizes its
storage XHTML, validates the canonical record, and prints a sanitized count
summary. It does not import or construct an HTTP transport and persists no
normalized content.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)

DEFAULT_RAW_ROOT = "data/raw"

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_SCHEMA = "schema"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CODES = {
    CATEGORY_UNEXPECTED: 1,
    CATEGORY_CONFIGURATION: 2,
    "invalid_page_id": 3,
    "raw_page_input": 4,
    "page_payload": 5,
    "storage_xhtml": 6,
    "timestamp": 7,
    "canonical_document": 8,
    CATEGORY_SCHEMA: 9,
}


class _ConfigurationError(Exception):
    """A sanitized command-line configuration failure."""


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        result = _run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION)
    except ConfluencePageNormalizationError as exc:
        return _fail(exc.category)
    except FoundationValidationError:
        return _fail(CATEGORY_SCHEMA)
    except BaseException:
        # Source text, identities, paths, URLs, and hashes from an unexpected
        # exception must never reach the terminal.
        return _fail(CATEGORY_UNEXPECTED)

    handled = result.counters.get("handled_macros", {})
    unhandled = result.counters.get("unhandled_macros", {})
    summary = {
        "status": "success",
        "canonical_document_valid": True,
        "warning_count": len(result.warnings),
        "handled_macro_count": _sum_counts(handled),
        "unhandled_macro_count": _sum_counts(unhandled),
        "toc_dropped": _safe_int(result.counters.get("toc_dropped")),
        "media_placeholder_count": _safe_int(
            result.counters.get("media_placeholders")
        ),
        "unsupported_element_count": _safe_int(
            result.counters.get("unsupported_elements")
        ),
    }
    sys.stdout.write(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    return 0


def _run(args: argparse.Namespace):
    try:
        raw_root = Path(args.raw_root)
    except (TypeError, ValueError) as exc:
        raise _ConfigurationError from exc

    use_case = NormalizeConfluencePage(
        raw_page_reader=ConfluencePageObservationStore(raw_root=raw_root),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    )
    result = use_case.execute(page_id=args.page_id, crawled_at=args.crawled_at)
    FoundationSchemaValidator().validate_record(
        "CanonicalDocument",
        result.canonical_document,
    )
    return result


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _sum_counts(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(_safe_int(count) for count in value.values())


def _fail(category: str) -> int:
    sys.stderr.write(
        json.dumps(
            {"status": "failed", "category": category},
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return EXIT_CODES.get(category, EXIT_CODES[CATEGORY_UNEXPECTED])


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """Never echo argv because it includes page and filesystem identity."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="normalize-confluence-page",
        description=(
            "Normalize one preserved Confluence page offline and validate one "
            "CanonicalDocument without persisting normalized content."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--crawled-at", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
