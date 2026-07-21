"""Collect and preserve M6B observations for one existing M6A raw page."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledgenexus.foundation.application.use_cases.collect_confluence_page_observations import (
    CollectConfluencePageObservations,
    PageObservationCollectionError,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageObservationAdapter,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
)

BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"
DEFAULT_RAW_ROOT = "data/raw"

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CODES = {
    CATEGORY_UNEXPECTED: 1,
    CATEGORY_CONFIGURATION: 2,
    "invalid_page_id": 3,
    "raw_page_input": 4,
    "restriction_http": 5,
    "attachment_http": 6,
    "response_size_limit": 7,
    "store": 8,
    "attachment_payload": 9,
    "pagination": 10,
}

_SUCCESS_CHECKS = (
    "raw_page_validated",
    "restrictions_collected",
    "restriction_bodies_preserved",
    "attachments_collected",
    "attachment_windows_preserved",
    "pagination_safe",
)


class _ConfigurationError(Exception):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        _run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION)
    except PageObservationCollectionError as exc:
        return _fail(exc.category)
    except BaseException:
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

    adapter = ConfluenceDataCenterPageObservationAdapter(transport=transport)
    store = ConfluencePageObservationStore(raw_root=Path(args.raw_root))
    use_case = CollectConfluencePageObservations(
        raw_page_reader=store,
        restriction_fetcher=adapter,
        attachment_fetcher=adapter,
        raw_observation_store=store,
        attachment_page_size=args.attachment_page_size,
        max_attachment_pages=args.max_attachment_pages,
    )
    use_case.execute(selected_page_id=args.page_id)


def _fail(category: str) -> int:
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
    def error(self, message: str) -> NoReturn:
        raise _ConfigurationError


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="collect-confluence-page-observations",
        description=(
            "Collect one page's restriction observations and attachment metadata. "
            f"Requires {BASE_URL_ENV} and {PAT_ENV} in the environment."
        ),
    )
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--attachment-page-size", type=_positive_int, required=True)
    parser.add_argument("--max-attachment-pages", type=_positive_int, required=True)
    parser.add_argument("--timeout-seconds", type=_positive_float, default=None)
    parser.add_argument("--max-response-bytes", type=_positive_int, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
