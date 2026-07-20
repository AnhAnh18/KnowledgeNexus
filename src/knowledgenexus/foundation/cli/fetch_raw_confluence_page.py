"""Operator entrypoint: fetch and preserve exactly one raw Confluence page.

Composes the approved production components and adds no HTTP, CQL, parsing,
normalization, ACL, or export behaviour of its own:

    environment credentials
        -> UrllibConfluenceHttpTransport (get_bytes)
        -> ConfluenceDataCenterPageAdapter
        -> FetchRawConfluencePage
        -> ConfluenceRawPageStore
        -> one deterministic raw page artifact + sanitized boolean status

Run with:

    python -m knowledgenexus.foundation.cli.fetch_raw_confluence_page ...

It makes exactly one page GET, never infers the page id/host/endpoint, never
retries, and prints only a sanitized completion status.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.fetch_raw_confluence_page import (  # noqa: E501
    FetchRawConfluencePage,
    RawPageFetchError,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageAdapter,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageStore

BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"
DEFAULT_RAW_ROOT = "data/raw"

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CODES = {
    CATEGORY_UNEXPECTED: 1,
    CATEGORY_CONFIGURATION: 2,
    "invalid_page_id": 3,
    "http": 4,
    "malformed_json": 5,
    "non_object_json": 6,
    "identity_mismatch": 7,
    "store": 8,
}

_SUCCESS_CHECKS = (
    "method_get",
    "status_success",
    "json_valid",
    "identity_match",
    "artifact_written",
    "hash_verified",
    "temporary_cleanup",
)


class _ConfigurationError(Exception):
    """A sanitized configuration failure raised before the use case runs."""


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        _run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION)
    except RawPageFetchError as exc:
        return _fail(exc.category)
    except BaseException:
        # An original exception may carry the URL, host, page id, title, or
        # credential; it must never reach the terminal.
        return _fail(CATEGORY_UNEXPECTED)

    for check in _SUCCESS_CHECKS:
        sys.stdout.write(f"{check}=true\n")
    return 0


def _run(args: argparse.Namespace) -> None:
    base_url = os.environ.get(BASE_URL_ENV)
    personal_access_token = os.environ.get(PAT_ENV)
    if not base_url or not personal_access_token:
        raise _ConfigurationError

    transport_kwargs: dict[str, object] = {
        "base_url": base_url,
        "personal_access_token": personal_access_token,
    }
    if args.timeout_seconds is not None:
        transport_kwargs["timeout_seconds"] = args.timeout_seconds
    if args.max_response_bytes is not None:
        transport_kwargs["max_response_bytes"] = args.max_response_bytes

    try:
        transport = UrllibConfluenceHttpTransport(**transport_kwargs)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _ConfigurationError from exc

    use_case = FetchRawConfluencePage(
        page_fetcher=ConfluenceDataCenterPageAdapter(transport=transport),
        raw_page_store=ConfluenceRawPageStore(raw_root=Path(args.raw_root)),
    )
    use_case.execute(page_id=args.page_id)


def _fail(category: str) -> int:
    import json

    sys.stderr.write(
        json.dumps(
            {"status": "failed", "category": category},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    return EXIT_CODES.get(category, EXIT_CODES[CATEGORY_UNEXPECTED])


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


class _SanitizedArgumentParser(argparse.ArgumentParser):
    """Never echoes argv: a mistyped flag must not print the page id."""

    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="fetch-raw-confluence-page",
        description=(
            "Fetch and preserve exactly one raw Confluence Data Center page. "
            f"Requires {BASE_URL_ENV} and {PAT_ENV} in the environment; the "
            "personal access token is never accepted on the command line."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--timeout-seconds", type=_positive_float, default=None)
    parser.add_argument("--max-response-bytes", type=_positive_int, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
