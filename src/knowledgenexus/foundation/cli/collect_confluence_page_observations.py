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
    PageObservationCollectionResult,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageObservationAdapter,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
)
from knowledgenexus.foundation.infrastructure.sidecars import (
    PreparedRestrictionSidecarTarget,
    RestrictionSidecarPublicationError,
    RestrictionSidecarSerializationError,
    RestrictionSidecarTargetError,
    prepare_restriction_sidecar_target,
    publish_restriction_sidecar,
    serialize_restriction_observations,
)

BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"
DEFAULT_RAW_ROOT = "data/raw"

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_UNEXPECTED = "unexpected"
CATEGORY_SIDECAR_TARGET = "sidecar_target"
CATEGORY_SIDECAR_SERIALIZATION = "sidecar_serialization"
CATEGORY_SIDECAR_PUBLICATION = "sidecar_publication"

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
    CATEGORY_SIDECAR_TARGET: 11,
    CATEGORY_SIDECAR_SERIALIZATION: 12,
    CATEGORY_SIDECAR_PUBLICATION: 13,
}

_SUCCESS_CHECKS = (
    "raw_page_validated",
    "restrictions_collected",
    "restriction_bodies_preserved",
    "attachments_collected",
    "attachment_windows_preserved",
    "pagination_safe",
)

_REPOSITORY_MARKERS = (
    Path("contracts/foundation/ACL_MATERIALIZATION_SPEC.md"),
    Path(
        "src/knowledgenexus/foundation/cli/"
        "collect_confluence_page_observations.py"
    ),
)


class _ConfigurationError(Exception):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    sidecar_written = False
    try:
        args = _parse_args(argv)
        prepared_target = _prepare_sidecar_target(args)
        result = _run(args)
        if prepared_target is not None:
            content = serialize_restriction_observations(
                result.restriction_observations
            )
            publish_restriction_sidecar(
                prepared_target=prepared_target,
                content=content,
            )
            sidecar_written = True
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION)
    except RestrictionSidecarTargetError:
        return _fail(CATEGORY_SIDECAR_TARGET)
    except RestrictionSidecarSerializationError:
        return _fail(CATEGORY_SIDECAR_SERIALIZATION)
    except RestrictionSidecarPublicationError:
        return _fail(CATEGORY_SIDECAR_PUBLICATION)
    except PageObservationCollectionError as exc:
        return _fail(exc.category)
    except BaseException:
        return _fail(CATEGORY_UNEXPECTED)

    for check in _SUCCESS_CHECKS:
        sys.stdout.write(f"{check}=true\n")
    if sidecar_written:
        sys.stdout.write("restriction_sidecar_written=true\n")
    return 0


def _run(args: argparse.Namespace) -> PageObservationCollectionResult:
    base_url, personal_access_token = _require_credentials()

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
    return use_case.execute(selected_page_id=args.page_id)


def _prepare_sidecar_target(
    args: argparse.Namespace,
) -> PreparedRestrictionSidecarTarget | None:
    target_path = args.restriction_observations_sidecar_out
    if target_path is None:
        return None
    repository_root = _resolve_repository_root(Path(__file__))
    return prepare_restriction_sidecar_target(
        target_path=target_path,
        repository_root=repository_root,
    )


def _resolve_repository_root(module_path: Path) -> Path:
    try:
        resolved_module = module_path.resolve(strict=True)
        repository_root = resolved_module.parents[4]
    except (IndexError, OSError, RuntimeError):
        raise RestrictionSidecarTargetError() from None
    for marker in _REPOSITORY_MARKERS:
        marker_path = repository_root / marker
        try:
            if not marker_path.is_file() or marker_path.is_symlink():
                raise RestrictionSidecarTargetError()
        except OSError:
            raise RestrictionSidecarTargetError() from None
    return repository_root


def _require_credentials() -> tuple[str, str]:
    base_url = os.environ.get(BASE_URL_ENV)
    personal_access_token = os.environ.get(PAT_ENV)
    if not base_url or not personal_access_token:
        raise _ConfigurationError
    return base_url, personal_access_token


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
    parser.add_argument(
        "--restriction-observations-sidecar-out",
        type=Path,
        default=None,
        help=(
            "Opt in to an external normalized restriction-observation "
            "sidecar. The absolute target must not already exist."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
