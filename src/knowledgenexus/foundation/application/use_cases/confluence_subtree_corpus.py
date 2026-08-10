"""Bounded, resumable Confluence subtree corpus harness.

This module is deliberately transport-agnostic.  Live adapters are injected by
the operator; the export path only consumes preserved artifacts and therefore
cannot accidentally open a network connection.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file

PACKET_FORMAT_VERSION = "confluence-subtree-indexing-packet-v1"
DEFAULT_BATCH_SIZE = 100
MAX_PAGES = 5000
DEFAULT_ACL_TAGS = ["restricted:unresolved"]
_FILES = ("documents.jsonl", "chunks.jsonl", "media_assets.jsonl", "packet_summary.json")


def _finite(name: str, value: object, *, maximum: int | None = None) -> int:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be a positive finite integer")
    return value


@dataclass(frozen=True)
class ConfluenceSubtreeCorpusConfig:
    max_pages: int
    batch_size: int = DEFAULT_BATCH_SIZE
    inventory_window: int = 100
    request_budget: int = 100_000
    retry_budget: int = 3
    page_bytes: int = 64 * 1024 * 1024
    total_bytes: int = 4 * 1024 * 1024 * 1024
    drawio_count: int = 5_000
    drawio_bytes: int = 4 * 1024 * 1024 * 1024
    free_disk_bytes: int = 1 * 1024 * 1024 * 1024
    stop_after_batches: int = 1

    def __post_init__(self) -> None:
        _finite("max_pages", self.max_pages, maximum=MAX_PAGES)
        if self.batch_size != DEFAULT_BATCH_SIZE:
            raise ValueError("batch_size must be 100")
        for name in ("inventory_window", "request_budget", "retry_budget", "page_bytes", "total_bytes", "drawio_count", "drawio_bytes", "free_disk_bytes", "stop_after_batches"):
            _finite(name, getattr(self, name))


def partition_page_ids(page_ids: Sequence[str], *, batch_size: int = DEFAULT_BATCH_SIZE, max_pages: int = MAX_PAGES) -> tuple[tuple[str, ...], ...]:
    """Validate and deterministically partition an inventory into batches."""
    if type(page_ids) not in (tuple, list):
        raise TypeError("page_ids must be a sequence")
    if type(batch_size) is not int or batch_size != DEFAULT_BATCH_SIZE:
        raise ValueError("batch_size must be 100")
    ids = tuple(page_ids)
    if len(ids) > max_pages or len(ids) > MAX_PAGES or any(type(p) is not str or not p or p in {".", ".."} or any(c in p for c in ("/", "\\", ":")) for p in ids) or len(set(ids)) != len(ids):
        raise ValueError("inventory is invalid or exceeds bound")
    return tuple(ids[i:i + batch_size] for i in range(0, len(ids), batch_size))


@dataclass(frozen=True)
class DrawioReference:
    parent_page_id: str
    filename: str
    source_version: str

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.parent_page_id, self.filename, self.source_version)):
            raise ValueError("drawio reference is invalid")


@dataclass(frozen=True)
class AttachmentMetadata:
    attachment_id: str
    parent_page_id: str
    filename: str
    source_version: str | None
    mime_type: str = "application/xml"

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.attachment_id, self.parent_page_id, self.filename)):
            raise TypeError("attachment metadata identity is invalid")
        if self.source_version is not None and (type(self.source_version) is not str or not self.source_version):
            raise TypeError("attachment source version is invalid")
        if type(self.mime_type) is not str or not self.mime_type:
            raise TypeError("attachment mime type is invalid")


def match_drawio_attachment(reference: DrawioReference, attachments: Iterable[AttachmentMetadata]) -> AttachmentMetadata | None:
    """Return one exact parent/name/version match; ambiguity fails closed."""
    if type(reference) is not DrawioReference:
        raise TypeError("reference is invalid")
    if type(attachments) not in (tuple, list):
        attachments = tuple(attachments)
    for item in attachments:
        if type(item) is not AttachmentMetadata:
            raise TypeError("attachment metadata is invalid")
    candidates = tuple(a for a in attachments if type(a) is AttachmentMetadata and a.parent_page_id == reference.parent_page_id and a.filename == reference.filename and a.source_version == reference.source_version and a.filename.lower().endswith((".drawio", ".drawio.xml", ".xml")))
    if len(candidates) > 1:
        raise ValueError("ambiguous drawio attachment")
    return candidates[0] if candidates else None


def _json_bytes(row: Mapping[str, object]) -> bytes:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


class SubtreePacketExporter:
    """Offline packet writer with deterministic repeat and no-clobber publish."""

    def __init__(self, *, validator: object, tokenizer: object | None = None) -> None:
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("validator is invalid")
        self._validator = validator
        self._tokenizer = tokenizer

    def publish(self, *, output_dir: Path, documents: Iterable[Mapping[str, object]], chunks: Iterable[Mapping[str, object]], media_assets: Iterable[Mapping[str, object]], summary: Mapping[str, object] | None = None) -> dict[str, object]:
        if not isinstance(output_dir, Path) or not output_dir.is_absolute() or output_dir.exists():
            raise ValueError("output directory must be an absolute new directory")
        parent = output_dir.parent
        if not parent.is_dir():
            raise ValueError("output parent must already exist")
        try:
            require_plain_directory_chain(parent)
        except Exception as exc:
            raise ValueError("output path is not a plain directory chain") from exc
        docs = tuple(sorted((dict(x) for x in documents), key=lambda x: str(x.get("document_id", ""))))
        chks = tuple(sorted((dict(x) for x in chunks), key=lambda x: str(x.get("chunk_id", ""))))
        media = tuple(sorted((dict(x) for x in media_assets), key=lambda x: str(x.get("media_id", ""))))
        if not docs or not chks:
            raise ValueError("packet records must be non-empty")
        doc_ids: set[str] = set()
        for row in docs:
            self._validator.validate_record("CanonicalDocument", row)
            ident = row.get("document_id")
            if type(ident) is not str or ident in doc_ids: raise ValueError("duplicate document id")
            doc_ids.add(ident)
        ids: set[str] = set()
        for row in chks:
            self._validator.validate_record("ChunkRecord", row)
            ident = row.get("chunk_id")
            if type(ident) is not str or ident in ids or row.get("document_id") not in doc_ids or row.get("acl_tags") != DEFAULT_ACL_TAGS: raise ValueError("invalid chunk closure")
            if row.get("content_kind") == "attachment_text": raise ValueError("attachment chunks are forbidden")
            ids.add(ident)
        mids: set[str] = set()
        for row in media:
            self._validator.validate_record("MediaAsset", row)
            ident = row.get("media_id")
            if type(ident) is not str or ident in mids or row.get("parent_document_id") not in doc_ids: raise ValueError("invalid media closure")
            mids.add(ident)
        payload = dict(summary or {})
        payload.update({"format_version": PACKET_FORMAT_VERSION, "document_count": len(docs), "chunk_count": len(chks), "media_asset_count": len(media), "acl_mode": "restricted_unresolved"})
        staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=str(parent)))
        try:
            for name, rows in (("documents.jsonl", docs), ("chunks.jsonl", chks), ("media_assets.jsonl", media)):
                (staging / name).write_bytes(b"".join(_json_bytes(row) for row in rows))
            (staging / "packet_summary.json").write_bytes(_json_bytes(payload))
            if output_dir.exists(): raise ValueError("packet already exists")
            staging.rename(output_dir)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {"format_version": PACKET_FORMAT_VERSION, "files_written": list(_FILES), "document_count": len(docs), "chunk_count": len(chks), "media_asset_count": len(media)}


def process_preserved_pages(*, processor: object, request: object) -> dict[str, object]:
    """Run the approved offline page-set pipeline over preserved generations.

    The processor is deliberately injected: this boundary cannot acquire a
    transport or silently substitute a different chunking profile.
    """
    execute = getattr(processor, "execute", None)
    if not callable(execute) or request is None:
        raise TypeError("processor/request is invalid")
    result = execute(request=request)
    for name in ("documents", "chunks", "metrics", "reference_intents_by_page"):
        if not hasattr(result, name):
            raise ValueError("page processing result is invalid")
    documents = tuple(dict(row) for row in result.documents)
    chunks = tuple(dict(row) for row in result.chunks)
    if not documents or not chunks:
        raise ValueError("page processing produced no records")
    return {"documents": documents, "chunks": chunks, "metrics": result.metrics, "reference_intents_by_page": result.reference_intents_by_page}


def capture_drawio_assets(*, references: Iterable[DrawioReference], list_attachments: Callable[[str], Iterable[AttachmentMetadata]], fetch_body: Callable[[AttachmentMetadata], bytes], process_body: Callable[[AttachmentMetadata, bytes], Mapping[str, object]], schema_validator: object | None = None, config: ConfluenceSubtreeCorpusConfig | None = None, persist_body: Callable[[AttachmentMetadata, bytes], object] | None = None,) -> dict[str, object]:
    """Resolve and process only exact Draw.io references.

    Metadata listing and body fetching are injected production seams.  The
    function never requests unrelated attachment bodies and reports failures
    without discarding the parent page records.
    """
    if not callable(list_attachments) or not callable(fetch_body) or not callable(process_body):
        raise TypeError("drawio callbacks are invalid")
    validate = getattr(schema_validator, "validate_record", None) if schema_validator is not None else None
    if schema_validator is not None and not callable(validate):
        raise TypeError("schema validator is invalid")
    if config is not None and type(config) is not ConfluenceSubtreeCorpusConfig:
        raise TypeError("config is invalid")
    if persist_body is not None and not callable(persist_body):
        raise TypeError("persist_body is invalid")
    assets: list[dict[str, object]] = []
    failures = 0
    observed = 0
    resolved = 0
    downloaded_bytes = 0
    for ref in references:
        if type(ref) is not DrawioReference:
            raise TypeError("drawio reference is invalid")
        observed += 1
        if config is not None and observed > config.drawio_count:
            failures += 1
            continue
        try:
            match = match_drawio_attachment(ref, tuple(list_attachments(ref.parent_page_id)))
            if match is None:
                failures += 1
                continue
            body = fetch_body(match)
            if type(body) is not bytes:
                raise ValueError("drawio body is invalid")
            if config is not None and (len(body) > config.drawio_bytes or downloaded_bytes + len(body) > config.drawio_bytes):
                failures += 1
                continue
            downloaded_bytes += len(body)
            asset = dict(process_body(match, body))
            if validate is not None:
                validate("MediaAsset", asset)
            if persist_body is not None:
                persist_body(match, body)
            assets.append(asset)
            resolved += 1
        except Exception:
            failures += 1
    return {"media_assets": tuple(assets), "drawio_references_observed": observed, "drawio_references_resolved": resolved, "drawio_assets_failed": failures}


class ConfluenceSubtreeCorpusHarness:
    """Small orchestration seam for independently resumable injected phases."""

    def __init__(self, *, config: ConfluenceSubtreeCorpusConfig, state_dir: Path) -> None:
        if type(config) is not ConfluenceSubtreeCorpusConfig:
            raise TypeError("config is invalid")
        if not isinstance(state_dir, Path) or not state_dir.is_absolute(): raise ValueError("state_dir must be absolute")
        require_plain_directory_chain(state_dir.parent)
        if state_dir.exists() and state_dir.is_dir(): require_plain_directory_chain(state_dir)
        self.config, self.state_dir = config, state_dir
        state_dir.mkdir(parents=True, exist_ok=True)

    def capture_pages(self, page_ids: Sequence[str], fetch_page: Callable[[str], bytes]) -> dict[str, object]:
        if not callable(fetch_page):
            raise TypeError("fetch_page is invalid")
        batches = partition_page_ids(page_ids, batch_size=self.config.batch_size, max_pages=self.config.max_pages)
        pages_root = self.state_dir / "pages"
        if pages_root.exists(): require_plain_directory_chain(pages_root)
        # Resume from the first batch that still has missing artifacts.
        start = next((i for i, batch in enumerate(batches) if any(not _valid_page_artifact(pages_root / f"{p}.bin") for p in batch)), len(batches))
        selected = batches[start:start + self.config.stop_after_batches]
        captured = 0
        total_bytes = sum(p.stat().st_size for p in pages_root.glob("*.bin") if _valid_page_artifact(p)) if pages_root.is_dir() else 0
        for batch in selected:
            for page_id in batch:
                target = self.state_dir / "pages" / f"{page_id}.bin"
                if _valid_page_artifact(target): continue
                body = fetch_page(page_id)
                if type(body) is not bytes or len(body) > self.config.page_bytes or total_bytes + len(body) > self.config.total_bytes: raise ValueError("page budget exhausted")
                usage = shutil.disk_usage(self.state_dir)
                if usage.free - len(body) < self.config.free_disk_bytes: raise ValueError("disk budget exhausted")
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(body)
                tmp.replace(target)
                captured += 1
                total_bytes += len(body)
        complete = start + len(selected) >= len(batches)
        return {"status": "complete" if complete else "stopped", "batches": len(selected), "captured_pages": captured}


def _valid_page_artifact(path: Path) -> bool:
    try:
        require_plain_file(path)
        return True
    except (OSError, ValueError):
        return False


__all__ = ["AttachmentMetadata", "ConfluenceSubtreeCorpusConfig", "ConfluenceSubtreeCorpusHarness", "DrawioReference", "SubtreePacketExporter", "capture_drawio_assets", "match_drawio_attachment", "partition_page_ids", "process_preserved_pages", "PACKET_FORMAT_VERSION"]
