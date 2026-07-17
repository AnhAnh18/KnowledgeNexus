"""Operator smoke runner for the approved Confluence Data Center inventory path.

Composes the approved production components and adds no HTTP, CQL, pagination,
parsing, normalization, scope, or report-serialization behaviour of its own:

    environment credentials
        -> UrllibConfluenceHttpTransport
        -> ConfluenceDataCenterInventoryAdapter
        -> BuildConfluenceInventory
        -> ConfluenceInventoryReportWriter
        -> local reports + non-sensitive smoke summary

Run with:

    python -m knowledgenexus.foundation.cli.confluence_inventory_smoke ...
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.build_confluence_inventory import (  # noqa: E501
    BuildConfluenceInventory,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_item import (
    ConfluenceInventoryItem,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterInventoryAdapter,
    ConfluenceDataCenterPaginationError,
    ConfluenceDataCenterPayloadError,
    ConfluenceDataCenterRequestError,
    ConfluenceHttpError,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.exporters.confluence_inventory_report_writer import (  # noqa: E501
    CSV_COLUMNS,
    INVENTORY_REPORT_FILE_NAME,
    PAGES_INVENTORY_FILE_NAME,
    ConfluenceInventoryReportWriter,
)

SUMMARY_FILE_NAME = "m5c_smoke_summary.json"
BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_OUTPUT_DIRECTORY = "output_directory"
CATEGORY_CONNECTION = "connection"
CATEGORY_AUTHENTICATION_OR_HTTP = "authentication_or_http"
CATEGORY_RESPONSE_CONTRACT = "response_contract"
CATEGORY_PAGINATION_LIMIT = "pagination_limit"
CATEGORY_REPORT_WRITE = "report_write"
CATEGORY_REPORT_VERIFICATION = "report_verification"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CODES = {
    CATEGORY_UNEXPECTED: 1,
    CATEGORY_CONFIGURATION: 2,
    CATEGORY_OUTPUT_DIRECTORY: 3,
    CATEGORY_CONNECTION: 4,
    CATEGORY_AUTHENTICATION_OR_HTTP: 5,
    CATEGORY_RESPONSE_CONTRACT: 6,
    CATEGORY_PAGINATION_LIMIT: 7,
    CATEGORY_REPORT_WRITE: 8,
    CATEGORY_REPORT_VERIFICATION: 9,
}

# The transport deliberately raises one sanitized error type without a status
# code or typed cause, so these literals mirror its messages. If a later
# reliability task introduces typed transport failures, replace this mapping.
_TRANSPORT_MESSAGE_CATEGORIES = (
    ("HTTP status", CATEGORY_AUTHENTICATION_OR_HTTP),
    ("non-JSON content type", CATEGORY_AUTHENTICATION_OR_HTTP),
    ("malformed JSON", CATEGORY_RESPONSE_CONTRACT),
    ("non-object JSON payload", CATEGORY_RESPONSE_CONTRACT),
    ("response size limit", CATEGORY_RESPONSE_CONTRACT),
)

# Header-shaped patterns, not bare words: a legitimate page may be titled
# "Authorization Guide", and the reports hold real inventory metadata.
_FORBIDDEN_OUTPUT_PATTERNS = (
    "Authorization: Bearer",
    "Set-Cookie:",
)

_SUMMARY_INT_FIELDS = (
    "total_items",
    "included_items",
    "excluded_subtree_items",
    "root_items",
    "maximum_relative_depth",
    "pages_inventory_jsonl_records",
    "inventory_report_csv_data_rows",
    "page_size",
    "max_search_pages",
)
_SUMMARY_HASH_FIELDS = (
    "pages_inventory_jsonl_sha256",
    "inventory_report_csv_sha256",
)
_SUMMARY_FIXED_FIELDS = {
    "status": "passed",
    "attachment_count_all_unknown": True,
    "root_labels_requested": False,
    "root_labels_interpretation": "unknown_not_requested",
}

_REPO_ROOT = Path(__file__).resolve().parents[4]


class SmokeFailure(Exception):
    """A sanitized, category-tagged smoke-run failure."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def main(argv: Sequence[str] | None = None) -> int:
    created_paths: list[Path] = []
    try:
        return _run(args=_parse_args(argv), created_paths=created_paths)
    except SystemExit as exc:
        # `--help` only: argparse prints its own text, which holds no argv value.
        return int(exc.code or 0)
    except SmokeFailure as failure:
        cleanup_incomplete = not _cleanup(created_paths)
        _emit_failure(category=failure.category, cleanup_incomplete=cleanup_incomplete)
        return EXIT_CODES[failure.category]
    except BaseException:
        # Never let an original exception reach stderr: it may carry the URL,
        # host, CQL, identifiers, titles, payload, or credential.
        cleanup_incomplete = not _cleanup(created_paths)
        _emit_failure(
            category=CATEGORY_UNEXPECTED,
            cleanup_incomplete=cleanup_incomplete,
        )
        return EXIT_CODES[CATEGORY_UNEXPECTED]


def _run(*, args: argparse.Namespace, created_paths: list[Path]) -> int:
    base_url, personal_access_token = _require_credentials()
    output_dir = _require_empty_output_dir(args.output_dir)
    config = _build_config(args)

    items = _collect_inventory(
        config=config,
        base_url=base_url,
        personal_access_token=personal_access_token,
        max_search_pages=args.max_search_pages,
    )

    jsonl_path = output_dir / PAGES_INVENTORY_FILE_NAME
    csv_path = output_dir / INVENTORY_REPORT_FILE_NAME
    summary_path = output_dir / SUMMARY_FILE_NAME
    try:
        ConfluenceInventoryReportWriter.write(output_dir=output_dir, items=items)
    except Exception as exc:
        raise SmokeFailure(CATEGORY_REPORT_WRITE) from exc
    # Only now are these reports demonstrably ours. The writer publishes with an
    # atomic no-clobber link and rolls its own links back on failure, so a target
    # that exists before it returns may belong to another process; registering a
    # pathname earlier would let cleanup delete that process's file.
    created_paths.extend((jsonl_path, csv_path))
    _require_exact_output_tree(
        output_dir,
        {PAGES_INVENTORY_FILE_NAME, INVENTORY_REPORT_FILE_NAME},
    )

    summary = _verify_and_build_summary(
        items=items,
        jsonl_path=jsonl_path,
        csv_path=csv_path,
        personal_access_token=personal_access_token,
        page_size=args.page_size,
        max_search_pages=args.max_search_pages,
    )
    summary_bytes = _render_summary(summary)
    _require_summary_is_safe(
        summary_bytes=summary_bytes,
        base_url=base_url,
        personal_access_token=personal_access_token,
    )

    _publish_summary(
        summary_path=summary_path,
        summary_bytes=summary_bytes,
        created_paths=created_paths,
    )
    _require_exact_output_tree(
        output_dir,
        {PAGES_INVENTORY_FILE_NAME, INVENTORY_REPORT_FILE_NAME, SUMMARY_FILE_NAME},
    )

    sys.stdout.write(summary_bytes.decode("utf-8"))
    return 0


def _publish_summary(
    *,
    summary_path: Path,
    summary_bytes: bytes,
    created_paths: list[Path],
) -> None:
    """Publish the success-only summary without clobbering another writer.

    Mirrors the M5A report writer: an exclusively created same-directory
    temporary, then an atomic no-clobber hard link. Registering a pathname is not
    ownership, so a path joins `created_paths` only once this runner has actually
    created it — before that, cleanup could delete a concurrent creator's file.

    The temporary is registered the moment it exists, so a failing write, flush,
    or close still leaves nothing behind: the runbook makes the summary's
    presence the proof that the run passed.
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=summary_path.parent,
            prefix=f".{summary_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            created_paths.append(temp_path)
            temp_file.write(summary_bytes)
    except OSError as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc

    try:
        os.link(temp_path, summary_path)
    except OSError as exc:
        # Includes FileExistsError: another process owns that name, so it must
        # not be replaced and must not be registered for cleanup.
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc
    created_paths.append(summary_path)

    try:
        temp_path.unlink()
    except OSError as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc


def _require_exact_output_tree(output_dir: Path, expected: set[str]) -> None:
    """Require the output directory to hold exactly `expected` as regular files.

    The M5A writer swallows failures when removing its own same-directory
    temporaries, so a leftover `.pages_inventory.jsonl.<random>.tmp` would hold a
    second copy of real inventory metadata while the run still reported success.
    Those temporaries are writer-owned, so fail closed and let the operator
    inspect rather than deleting entries this runner did not create.
    """
    try:
        entries = list(output_dir.iterdir())
    except OSError as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc
    if {entry.name for entry in entries} != expected:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)


def _collect_inventory(
    *,
    config: ConfluenceSourceConfig,
    base_url: str,
    personal_access_token: str,
    max_search_pages: int,
) -> tuple[ConfluenceInventoryItem, ...]:
    try:
        transport = UrllibConfluenceHttpTransport(
            base_url=base_url,
            personal_access_token=personal_access_token,
        )
    except (TypeError, ValueError) as exc:
        raise SmokeFailure(CATEGORY_CONFIGURATION) from exc

    adapter = ConfluenceDataCenterInventoryAdapter(
        transport=transport,
        max_search_pages=max_search_pages,
    )
    try:
        return BuildConfluenceInventory(inventory_port=adapter).execute(config=config)
    except ConfluenceDataCenterPaginationError as exc:
        raise SmokeFailure(CATEGORY_PAGINATION_LIMIT) from exc
    except ConfluenceDataCenterRequestError as exc:
        raise SmokeFailure(_categorize_request_error(exc)) from exc
    except ConfluenceHttpError as exc:
        raise SmokeFailure(CATEGORY_CONNECTION) from exc
    except ConfluenceDataCenterPayloadError as exc:
        raise SmokeFailure(CATEGORY_RESPONSE_CONTRACT) from exc
    except (TypeError, ValueError) as exc:
        raise SmokeFailure(CATEGORY_CONFIGURATION) from exc


def _categorize_request_error(error: ConfluenceDataCenterRequestError) -> str:
    message = str(error)
    for marker, category in _TRANSPORT_MESSAGE_CATEGORIES:
        if marker in message:
            return category
    return CATEGORY_CONNECTION


def _verify_and_build_summary(
    *,
    items: tuple[ConfluenceInventoryItem, ...],
    jsonl_path: Path,
    csv_path: Path,
    personal_access_token: str,
    page_size: int,
    max_search_pages: int,
) -> dict[str, object]:
    total_items = len(items)
    included_items = sum(1 for item in items if item.scope_status == "included")
    excluded_subtree_items = sum(
        1 for item in items if item.scope_status == "excluded_subtree"
    )
    root_items = sum(1 for item in items if not item.ancestor_page_ids)

    if total_items <= 0:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    if root_items != 1:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    if total_items != included_items + excluded_subtree_items:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    if any(item.attachment_count is not None for item in items):
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)

    # Reopen both published reports: the writer's return value is its own input
    # count, not evidence about the bytes on disk.
    jsonl_records = _count_jsonl_records(jsonl_path)
    csv_data_rows = _count_csv_data_rows(csv_path)
    if jsonl_records != total_items or csv_data_rows != total_items:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)

    for path in (jsonl_path, csv_path):
        _require_report_has_no_credential_material(
            path=path,
            personal_access_token=personal_access_token,
        )

    return {
        **_SUMMARY_FIXED_FIELDS,
        "total_items": total_items,
        "included_items": included_items,
        "excluded_subtree_items": excluded_subtree_items,
        "root_items": root_items,
        "maximum_relative_depth": max(
            len(item.ancestor_page_ids) for item in items
        ),
        "pages_inventory_jsonl_records": jsonl_records,
        "inventory_report_csv_data_rows": csv_data_rows,
        "pages_inventory_jsonl_sha256": _sha256(jsonl_path),
        "inventory_report_csv_sha256": _sha256(csv_path),
        "page_size": page_size,
        "max_search_pages": max_search_pages,
    }


def _count_jsonl_records(path: Path) -> int:
    records = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip() == "":
                    continue
                json.loads(line)
                records += 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc
    return records


def _count_csv_data_rows(path: Path) -> int:
    # Titles and page paths may legally contain commas, quotes, or newlines, so
    # only the csv module can count logical records.
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc
            if tuple(header) != CSV_COLUMNS:
                raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
            return sum(1 for row in reader if row)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc


def _require_report_has_no_credential_material(
    *,
    path: Path,
    personal_access_token: str,
) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc
    if personal_access_token in text:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    if any(pattern in text for pattern in _FORBIDDEN_OUTPUT_PATTERNS):
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)


def _render_summary(summary: dict[str, object]) -> bytes:
    return (
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _require_summary_is_safe(
    *,
    summary_bytes: bytes,
    base_url: str,
    personal_access_token: str,
) -> None:
    """Prove the summary carries no source, scope, connection, or secret value.

    The source ID, space key, root page ID, and excluded page IDs are excluded
    structurally: every key is allowlisted and every value is an integer, a
    boolean, or a fixed literal. They are not also matched as text because a
    numeric page ID collides with a count or a hash substring, which would fail
    a legitimate run.
    """
    text = summary_bytes.decode("utf-8")
    if personal_access_token in text or base_url in text:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)

    summary = json.loads(text)
    expected_keys = {
        *_SUMMARY_FIXED_FIELDS,
        *_SUMMARY_INT_FIELDS,
        *_SUMMARY_HASH_FIELDS,
    }
    if set(summary) != expected_keys:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    for field, expected_value in _SUMMARY_FIXED_FIELDS.items():
        if summary[field] != expected_value:
            raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    for field in _SUMMARY_INT_FIELDS:
        value = summary[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)
    for field in _SUMMARY_HASH_FIELDS:
        value = summary[field]
        if not isinstance(value, str) or len(value) != 64:
            raise SmokeFailure(CATEGORY_REPORT_VERIFICATION)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SmokeFailure(CATEGORY_REPORT_VERIFICATION) from exc


def _require_credentials() -> tuple[str, str]:
    base_url = os.environ.get(BASE_URL_ENV)
    personal_access_token = os.environ.get(PAT_ENV)
    if not base_url or not personal_access_token:
        raise SmokeFailure(CATEGORY_CONFIGURATION)
    return base_url, personal_access_token


def _require_empty_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    if _is_inside(resolved, _REPO_ROOT):
        raise SmokeFailure(CATEGORY_OUTPUT_DIRECTORY)
    if not resolved.exists() or not resolved.is_dir():
        raise SmokeFailure(CATEGORY_OUTPUT_DIRECTORY)
    try:
        if any(resolved.iterdir()):
            raise SmokeFailure(CATEGORY_OUTPUT_DIRECTORY)
    except OSError as exc:
        raise SmokeFailure(CATEGORY_OUTPUT_DIRECTORY) from exc
    return resolved


def _is_inside(path: Path, parent: Path) -> bool:
    normalized_path = os.path.normcase(str(path))
    normalized_parent = os.path.normcase(str(parent))
    return normalized_path == normalized_parent or normalized_path.startswith(
        normalized_parent + os.sep
    )


def _build_config(args: argparse.Namespace) -> ConfluenceSourceConfig:
    try:
        return ConfluenceSourceConfig(
            source_id=args.source_id,
            space_key=args.space_key,
            include_roots=(ConfluenceIncludeRoot(page_id=args.root_page_id),),
            exclude_subtrees=tuple(
                ConfluenceExcludeSubtree(page_id=page_id)
                for page_id in args.exclude_subtree_page_id
            ),
            page_size=args.page_size,
        )
    except (TypeError, ValueError) as exc:
        raise SmokeFailure(CATEGORY_CONFIGURATION) from exc


def _cleanup(created_paths: list[Path]) -> bool:
    """Remove only files this run created. Never touch the output directory."""
    complete = True
    for path in reversed(created_paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            complete = False
    return complete


def _emit_failure(*, category: str, cleanup_incomplete: bool) -> None:
    sys.stderr.write(
        json.dumps(
            {
                "status": "failed",
                "category": category,
                "cleanup_incomplete": cleanup_incomplete,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """An argument parser that never echoes argv.

    `argparse.ArgumentParser.error()` writes the offending arguments to stderr
    before raising, which would print a mistyped `--pat <token>`, base URL, space
    key, or page ID verbatim. Every parse failure funnels through `error()`, so
    overriding it keeps argv out of the output entirely.
    """

    def error(self, message: str) -> NoReturn:
        raise SmokeFailure(CATEGORY_CONFIGURATION)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="confluence-inventory-smoke",
        description=(
            "Read-only Confluence Data Center metadata inventory smoke run. "
            f"Requires {BASE_URL_ENV} and {PAT_ENV} in the environment; the "
            "personal access token is never accepted on the command line."
        ),
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--space-key", required=True)
    parser.add_argument("--root-page-id", required=True)
    parser.add_argument("--page-size", required=True, type=_positive_int)
    parser.add_argument("--max-search-pages", required=True, type=_positive_int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--exclude-subtree-page-id",
        action="append",
        default=[],
        metavar="PAGE_ID",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
