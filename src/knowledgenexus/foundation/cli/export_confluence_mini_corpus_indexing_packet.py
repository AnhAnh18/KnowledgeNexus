"""Export an offline M8 mini corpus as a bounded Indexing smoke-test packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import NoReturn, Sequence

from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.cli.accept_confluence_mini_corpus import (
    MiniCorpusOperatorInputError,
    fingerprint_mini_corpus_tree,
    load_mini_corpus_selection,
    safe_mini_corpus_path,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetError,
    ConfluencePageSetRequest,
    ConfluencePageSetResult,
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
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


PACKET_FORMAT_VERSION = "m8ax-indexing-packet-v1"
DOCUMENTS_FILE = "documents.jsonl"
CHUNKS_FILE = "chunks.jsonl"
SUMMARY_FILE = "packet_summary.json"
_EXPECTED_FILES = frozenset({DOCUMENTS_FILE, CHUNKS_FILE, SUMMARY_FILE})
_DEFAULT_DENY = ["restricted:unresolved"]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class _ExportError(Exception):
    pass


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise MiniCorpusOperatorInputError


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        summary = _run(args)
    except MiniCorpusOperatorInputError:
        return _fail("configuration")
    except ConfluencePageSetError as exc:
        return _fail(exc.category.value)
    except _ExportError:
        return _fail("packet_export")
    except (TypeError, ValueError, OSError, json.JSONDecodeError):
        return _fail("external_input")
    except Exception:
        return _fail("unexpected")
    sys.stdout.write(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    return 0


def _run(args: argparse.Namespace) -> dict[str, object]:
    raw_root = safe_mini_corpus_path(args.data_root)
    selection_path = safe_mini_corpus_path(args.selection_path)
    profile_path = safe_mini_corpus_path(args.profile_path)
    tokenizer_assets_dir = safe_mini_corpus_path(args.tokenizer_assets_dir)
    output_dir = _safe_output_directory(args.output_dir)
    if (
        not raw_root.is_dir()
        or not selection_path.is_file()
        or not profile_path.is_file()
        or not tokenizer_assets_dir.is_dir()
    ):
        raise MiniCorpusOperatorInputError
    run_id = CrawlRunId(args.run_id)
    items = load_mini_corpus_selection(selection_path)
    request = ConfluencePageSetRequest(
        run_id=run_id,
        generation_id=run_id,
        items=items,
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    )
    profile = load_chunking_profile(profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()

    def process_once() -> ConfluencePageSetResult:
        return ProcessConfluencePageSet(
            chunking_profile=profile,
            tokenizer=tokenizer,
            raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
            raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
            storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
            schema_validator=validator,
        ).execute(request=request)

    source_before = fingerprint_mini_corpus_tree(raw_root)
    selection_before = _sha256_file(selection_path)
    first = process_once()
    second = process_once()
    if first.to_canonical_json() != second.to_canonical_json():
        raise _ExportError
    _validate_result(first, validator=validator)
    if source_before != fingerprint_mini_corpus_tree(raw_root):
        raise _ExportError
    if selection_before != _sha256_file(selection_path):
        raise _ExportError

    packet = _publish_packet(
        output_dir=output_dir,
        result=first,
        chunker_version=profile.chunker_version,
    )
    if source_before != fingerprint_mini_corpus_tree(raw_root):
        raise _ExportError
    if selection_before != _sha256_file(selection_path):
        raise _ExportError
    return {
        "acl_mode": "restricted_unresolved",
        "all_records_schema_valid": True,
        "chunk_count": first.metrics.chunk_count,
        "deterministic_repeat": True,
        "document_count": first.metrics.document_count,
        "exact_local_tokenizer_verified": True,
        "failed_pages": first.metrics.failed_pages,
        "files_written": packet["files_written"],
        "format_version": PACKET_FORMAT_VERSION,
        "no_network": True,
        "packet_published": True,
        "requested_pages": first.metrics.requested_pages,
        "selection_unchanged": True,
        "source_unchanged": True,
        "status": "complete",
        "succeeded_pages": first.metrics.succeeded_pages,
    }


def _validate_result(
    result: ConfluencePageSetResult,
    *,
    validator: FoundationSchemaValidator,
) -> None:
    if type(result) is not ConfluencePageSetResult:
        raise _ExportError
    document_ids: set[str] = set()
    for record in result.documents:
        validator.validate_record("CanonicalDocument", record)
        document_id = record.get("document_id")
        if type(document_id) is not str or not document_id or document_id in document_ids:
            raise _ExportError
        document_ids.add(document_id)
    chunk_ids: set[str] = set()
    for record in result.chunks:
        validator.validate_record("ChunkRecord", record)
        chunk_id = record.get("chunk_id")
        if type(chunk_id) is not str or not chunk_id or chunk_id in chunk_ids:
            raise _ExportError
        if record.get("document_id") not in document_ids:
            raise _ExportError
        if record.get("acl_tags") != _DEFAULT_DENY:
            raise _ExportError
        chunk_ids.add(chunk_id)
    if len(document_ids) != result.metrics.document_count:
        raise _ExportError
    if len(chunk_ids) != result.metrics.chunk_count:
        raise _ExportError


def _publish_packet(
    *,
    output_dir: Path,
    result: ConfluencePageSetResult,
    chunker_version: str,
) -> dict[str, object]:
    parent = output_dir.parent
    staging = parent / f".{output_dir.name}.{uuid.uuid4().hex}.tmp"
    if output_dir.exists() or staging.exists():
        raise _ExportError
    try:
        staging.mkdir()
        documents_path = staging / DOCUMENTS_FILE
        chunks_path = staging / CHUNKS_FILE
        _write_jsonl(documents_path, result.documents)
        _write_jsonl(chunks_path, result.chunks)
        summary = {
            "acl_mode": "restricted_unresolved",
            "chunk_count": result.metrics.chunk_count,
            "chunker_version": chunker_version,
            "content_kind_counts": dict(result.metrics.content_kind_counts),
            "document_count": result.metrics.document_count,
            "files": {
                DOCUMENTS_FILE: _file_metadata(documents_path),
                CHUNKS_FILE: _file_metadata(chunks_path),
            },
            "format_version": PACKET_FORMAT_VERSION,
            "intended_use": "offline_indexing_smoke_test",
            "warning_count": result.metrics.warning_count,
        }
        _write_json_bytes(
            staging / SUMMARY_FILE,
            json.dumps(
                summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n",
        )
        actual = frozenset(path.name for path in staging.iterdir())
        if actual != _EXPECTED_FILES:
            raise _ExportError
        staging.rename(output_dir)
        return {"files_written": len(_EXPECTED_FILES)}
    except Exception:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except OSError:
            pass
        raise _ExportError from None


def _write_jsonl(path: Path, records: tuple[dict[str, object], ...]) -> None:
    hasher_input = bytearray()
    for record in records:
        try:
            line = json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, OverflowError):
            raise _ExportError from None
        hasher_input.extend(line)
        hasher_input.extend(b"\n")
    _write_json_bytes(path, bytes(hasher_input))


def _write_json_bytes(path: Path, content: bytes) -> None:
    if path.exists() or not path.parent.is_dir():
        raise _ExportError
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise _ExportError from None


def _file_metadata(path: Path) -> dict[str, object]:
    return {
        "byte_count": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_output_directory(value: object) -> Path:
    path = safe_mini_corpus_path(value)
    try:
        path.resolve(strict=False).relative_to(_REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise MiniCorpusOperatorInputError
    if path.exists() or not path.parent.is_dir() or path.parent.is_symlink():
        raise MiniCorpusOperatorInputError
    return path


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedParser(add_help=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--selection-path", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def _fail(category: str) -> int:
    sys.stderr.write(
        json.dumps(
            {"category": category, "status": "failed"},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
