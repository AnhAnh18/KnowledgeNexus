"""Aggregate-only acceptance command for a bounded M8 page selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import NoReturn, Sequence

from knowledgenexus.foundation.application.use_cases.accept_confluence_mini_corpus import (
    AcceptConfluenceMiniCorpus,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_mini_corpus_acceptance import (
    MiniCorpusAcceptanceError,
    MiniCorpusAcceptanceRequest,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageWorkItem,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    load_chunking_profile,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class MiniCorpusOperatorInputError(Exception):
    """Shared sanitized operator-input failure for bounded mini-corpus CLIs.

    Both `accept_confluence_mini_corpus` and
    `export_confluence_mini_corpus_indexing_packet` raise and catch this
    exact exception type, so a rejected operator input (bad path, missing
    parent, argparse failure, ...) is always reported as `"configuration"`
    rather than falling through to the generic `"unexpected"` category.
    """


_MAX_SELECTION_BYTES = 128 * 1024


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise MiniCorpusOperatorInputError


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        summary = _run(args)
    except MiniCorpusOperatorInputError:
        return _fail("configuration")
    except MiniCorpusAcceptanceError as exc:
        return _fail(exc.category.value)
    except (TypeError, ValueError, OSError, json.JSONDecodeError, ConfluenceRawPageStoreError):
        return _fail("external_input")
    except BaseException:
        return _fail("unexpected")
    payload = json.loads(summary.to_bytes())
    payload["summary_digest"] = summary.digest()
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    return 0


def _run(args: argparse.Namespace):
    raw_root = _safe_path(args.data_root)
    profile_path = _safe_path(args.profile_path)
    tokenizer_assets_dir = _safe_path(args.tokenizer_assets_dir)
    selection_path = _safe_path(args.selection_path)
    if not raw_root.is_dir() or not profile_path.is_file() or not tokenizer_assets_dir.is_dir() or not selection_path.is_file():
        raise MiniCorpusOperatorInputError
    run_id = CrawlRunId(args.run_id)
    generation_id = CrawlRunId(args.generation_id)
    items = _load_selection(selection_path)
    request = MiniCorpusAcceptanceRequest(
        run_id=run_id,
        generation_id=generation_id,
        items=items,
    )
    profile = load_chunking_profile(profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )

    def store_factory() -> ConfluenceRawPageGenerationStore:
        return ConfluenceRawPageGenerationStore(raw_root=raw_root)

    def source_fingerprint() -> str:
        store = store_factory()
        digest = hashlib.sha256()
        for ordinal, item in enumerate(request.items, start=1):
            path = store.resolve_page_path(run_id=request.run_id, page_id=item.page_id)
            details = os.lstat(path)
            if not os.path.isfile(path) or os.path.islink(path):
                raise OSError
            digest.update(str(ordinal).encode("ascii"))
            digest.update(str(details.st_size).encode("ascii"))
            digest.update(str(details.st_mtime_ns).encode("ascii"))
            with path.open("rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
        return digest.hexdigest()

    def write_fingerprint() -> str:
        return _tree_fingerprint(raw_root)

    return AcceptConfluenceMiniCorpus(
        chunking_profile=profile,
        tokenizer=tokenizer,
        raw_page_store_factory=store_factory,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        source_fingerprint=source_fingerprint,
        write_fingerprint=write_fingerprint,
    ).execute(request=request)


def _load_selection(path: Path) -> tuple[ConfluencePageWorkItem, ...]:
    try:
        if path.stat().st_size > _MAX_SELECTION_BYTES:
            raise MiniCorpusOperatorInputError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise MiniCorpusOperatorInputError from None
    if type(payload) is not list or not 10 <= len(payload) <= 20:
        raise MiniCorpusOperatorInputError
    items: list[ConfluencePageWorkItem] = []
    try:
        for entry in payload:
            if type(entry) is not dict or set(entry) != {
                "page_id",
                "crawled_at",
                "expected_source_version",
            }:
                raise MiniCorpusOperatorInputError
            items.append(
                ConfluencePageWorkItem(
                    page_id=entry["page_id"],
                    crawled_at=entry["crawled_at"],
                    expected_source_version=entry["expected_source_version"],
                )
            )
    except (TypeError, ValueError):
        raise MiniCorpusOperatorInputError from None
    return tuple(items)


def _safe_path(value: object) -> Path:
    if type(value) is not str or not value:
        raise MiniCorpusOperatorInputError
    path = Path(value)
    if not path.is_absolute():
        raise MiniCorpusOperatorInputError
    forbidden = {".env", ".local_ai", "evidence", "tool_trreport"}
    if any(part.lower() in forbidden for part in path.parts):
        raise MiniCorpusOperatorInputError
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        raise MiniCorpusOperatorInputError from None
    if any(part.lower() in forbidden for part in resolved.parts):
        raise MiniCorpusOperatorInputError
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise MiniCorpusOperatorInputError
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


def _tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    try:
        entries = sorted(root.rglob("*"), key=lambda entry: entry.as_posix())
        for entry in entries:
            if _is_reparse_point(entry):
                raise OSError
            relative = entry.relative_to(root).as_posix().encode("utf-8")
            digest.update(relative)
            if entry.is_dir():
                digest.update(b"D")
                continue
            if not entry.is_file():
                raise OSError
            digest.update(b"F")
            with entry.open("rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
    except (OSError, ValueError):
        raise MiniCorpusOperatorInputError from None
    return digest.hexdigest()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedParser(add_help=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--selection-path", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    return parser.parse_args(argv)


def _fail(category: str) -> int:
    sys.stderr.write(json.dumps({"status": "failed", "category": category}, sort_keys=True) + "\n")
    return 1


# Public operator-input seams shared by bounded mini-corpus commands.  The
# underscore names remain as compatibility aliases for the approved M8-AC
# tests and callers.
load_mini_corpus_selection = _load_selection
safe_mini_corpus_path = _safe_path
fingerprint_mini_corpus_tree = _tree_fingerprint


if __name__ == "__main__":
    raise SystemExit(main())
