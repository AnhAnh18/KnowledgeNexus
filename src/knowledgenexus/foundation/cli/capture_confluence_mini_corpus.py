"""Controlled read-only capture for one M8 mini-corpus generation.

The command accepts an external file containing 10--20 explicitly selected
Confluence page IDs.  Each page is fetched exactly once through the approved
M6A adapter, validated by the approved raw-page mapper, wrapped in the M7
generation envelope, and atomically published through the generation store.

Credentials are environment-only.  Output is aggregate-only except for the
operator-supplied run ID, which is needed by the subsequent M8-AC command.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Protocol

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageAdapter,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)


BASE_URL_ENV = "CONFLUENCE_BASE_URL"
PAT_ENV = "CONFLUENCE_PAT"
_MAX_PAGE_IDS_BYTES = 128 * 1024
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_FORBIDDEN_PARTS = frozenset({".env", ".local_ai", "evidence", "tool_trreport"})

_EXIT_CODES = {
    "unexpected": 1,
    "configuration": 2,
    "page_fetch": 3,
    "page_mapping": 4,
    "raw_publication": 5,
    "selection_publication": 6,
}


class _ConfigurationError(Exception):
    pass


class _CaptureError(Exception):
    def __init__(self, category: str, *, published_pages: int = 0) -> None:
        self.category = category
        self.published_pages = published_pages
        super().__init__(category)


class _PageFetcher(Protocol):
    def fetch_page_response_raw(self, *, page_id: str): ...


class _PageMapper(Protocol):
    def map_page(self, *, raw_bytes: bytes, expected_page_id: str): ...


class _GenerationStore(Protocol):
    def publish_page(self, *, envelope: ConfluenceRawPageEnvelope): ...


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise _ConfigurationError


def _safe_external_path(value: object) -> Path:
    if type(value) is not str or not value:
        raise _ConfigurationError
    path = Path(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise _ConfigurationError
    if any(part.lower() in _FORBIDDEN_PARTS for part in path.parts):
        raise _ConfigurationError
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        pass
    except OSError:
        raise _ConfigurationError from None
    else:
        raise _ConfigurationError
    if any(part.lower() in _FORBIDDEN_PARTS for part in resolved.parts):
        raise _ConfigurationError
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise _ConfigurationError
    return path


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if callable(is_junction) and is_junction(path):
        return True
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _load_page_ids(path: Path) -> tuple[str, ...]:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_PAGE_IDS_BYTES:
            raise _ConfigurationError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _ConfigurationError from None
    if type(payload) is not list or not 10 <= len(payload) <= 20:
        raise _ConfigurationError
    try:
        page_ids = tuple(require_confluence_page_id(value) for value in payload)
    except (TypeError, ValueError):
        raise _ConfigurationError from None
    if len(set(page_ids)) != len(page_ids):
        raise _ConfigurationError
    return page_ids


def _rfc3339_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _capture_pages(
    *,
    run_id: CrawlRunId,
    page_ids: tuple[str, ...],
    page_fetcher: _PageFetcher,
    page_mapper: _PageMapper,
    generation_store: _GenerationStore,
) -> tuple[dict[str, str], ...]:
    selection: list[dict[str, str]] = []
    published = 0
    for page_id in page_ids:
        try:
            response = page_fetcher.fetch_page_response_raw(page_id=page_id)
            if response.status_code != 200 or type(response.body) is not bytes:
                raise ValueError
            raw_bytes = response.body
        except Exception:
            raise _CaptureError("page_fetch", published_pages=published) from None
        try:
            source = page_mapper.map_page(
                raw_bytes=raw_bytes,
                expected_page_id=page_id,
            )
            source_version = source.source_version
            if type(source_version) is not str or not source_version:
                raise ValueError
            envelope = ConfluenceRawPageEnvelope.capture(
                run_id=run_id,
                page_id=page_id,
                source_version=source_version,
                http_status=response.status_code,
                body_bytes=raw_bytes,
            )
        except Exception:
            raise _CaptureError("page_mapping", published_pages=published) from None
        try:
            artifact = generation_store.publish_page(envelope=envelope)
            if artifact.outcome is not ConfluenceRawPagePublicationOutcome.PUBLISHED:
                raise ValueError
        except Exception:
            raise _CaptureError("raw_publication", published_pages=published) from None
        published += 1
        selection.append(
            {
                "page_id": page_id,
                "crawled_at": _rfc3339_now(),
                "expected_source_version": source_version,
            }
        )
    return tuple(selection)


def _hard_link_preflight(parent: Path) -> None:
    first: Path | None = None
    second: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=parent,
            prefix=".m8ac-hardlink-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(b"m8ac")
            handle.flush()
            os.fsync(handle.fileno())
            first = Path(handle.name)
        second = first.with_name(first.name + ".link")
        os.link(first, second)
        if second.read_bytes() != b"m8ac":
            raise OSError
    except OSError:
        raise _ConfigurationError from None
    finally:
        for candidate in (second, first):
            if candidate is not None:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass


def _publish_selection(path: Path, selection: tuple[dict[str, str], ...]) -> None:
    body = (
        json.dumps(
            selection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=".m8ac-selection-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.link(temporary, path)
    except (OSError, TypeError, ValueError):
        raise _CaptureError(
            "selection_publication",
            published_pages=len(selection),
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        prog="capture-confluence-mini-corpus",
        description="Capture 10-20 explicit Confluence pages into one M8 generation.",
    )
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--page-ids-path", required=True)
    parser.add_argument("--selection-out", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-response-bytes", type=int, default=16 * 1024 * 1024)
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> tuple[str, int]:
    data_root = _safe_external_path(args.data_root)
    page_ids_path = _safe_external_path(args.page_ids_path)
    selection_out = _safe_external_path(args.selection_out)
    if not data_root.is_dir() or not page_ids_path.is_file():
        raise _ConfigurationError
    if not selection_out.parent.is_dir() or selection_out.exists():
        raise _ConfigurationError
    if (
        type(args.timeout_seconds) is not float
        or not math.isfinite(args.timeout_seconds)
        or args.timeout_seconds <= 0
    ):
        raise _ConfigurationError
    if type(args.max_response_bytes) is not int or args.max_response_bytes <= 0:
        raise _ConfigurationError
    try:
        run_id = CrawlRunId(args.run_id)
    except (TypeError, ValueError):
        raise _ConfigurationError from None
    generation_path = data_root / "confluence" / "generations" / str(run_id)
    if os.path.lexists(generation_path):
        raise _ConfigurationError
    page_ids = _load_page_ids(page_ids_path)

    # Publication capability must be proven before credentials are read and
    # before any request can be issued.
    _hard_link_preflight(data_root)
    if selection_out.parent.resolve() != data_root.resolve():
        _hard_link_preflight(selection_out.parent)

    base_url = os.environ.get(BASE_URL_ENV)
    personal_access_token = os.environ.get(PAT_ENV)
    if not base_url or not personal_access_token:
        raise _ConfigurationError
    try:
        transport = UrllibConfluenceHttpTransport(
            base_url=base_url,
            personal_access_token=personal_access_token,
            timeout_seconds=args.timeout_seconds,
            max_response_bytes=args.max_response_bytes,
        )
        page_fetcher = ConfluenceDataCenterPageAdapter(transport=transport)
        mapper = ConfluenceDataCenterRawPageMapper()
        store = ConfluenceRawPageGenerationStore(raw_root=data_root)
    except (TypeError, ValueError):
        raise _ConfigurationError from None
    selection = _capture_pages(
        run_id=run_id,
        page_ids=page_ids,
        page_fetcher=page_fetcher,
        page_mapper=mapper,
        generation_store=store,
    )
    _publish_selection(selection_out, selection)
    return str(run_id), len(selection)


def _write_failure(category: str, *, published_pages: int = 0) -> int:
    sys.stderr.write(
        json.dumps(
            {
                "status": "failed",
                "category": category,
                "published_pages": published_pages,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return _EXIT_CODES.get(category, _EXIT_CODES["unexpected"])


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        run_id, count = _run(args)
    except _ConfigurationError:
        return _write_failure("configuration")
    except _CaptureError as exc:
        return _write_failure(
            exc.category,
            published_pages=exc.published_pages,
        )
    except Exception:
        return _write_failure("unexpected")
    sys.stdout.write(
        json.dumps(
            {
                "status": "success",
                "run_id": run_id,
                "requested_pages": count,
                "published_pages": count,
                "selection_written": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
