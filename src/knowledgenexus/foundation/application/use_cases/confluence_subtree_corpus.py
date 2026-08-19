"""Bounded, resumable Confluence subtree corpus harness.

This module is deliberately transport-agnostic.  Live adapters are injected by
the operator; the export path only consumes preserved artifacts and therefore
cannot accidentally open a network connection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file

PACKET_FORMAT_VERSION = "confluence-subtree-indexing-packet-v1"
DEFAULT_BATCH_SIZE = 100
MAX_PAGES = 5000
DEFAULT_ACL_TAGS = ["restricted:unresolved"]
logger = logging.getLogger(__name__)

_FILES = ("documents.jsonl", "chunks.jsonl", "media_assets.jsonl", "packet_summary.json")
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_DRAWIO_STATE_FORMAT_VERSION = "confluence-subtree-drawio-state-v1"
_DRAWIO_STATE_FIELDS = frozenset({
    "format_version", "run_id", "generation_id", "selection_identity",
    "observed", "resolutions", "failed", "downloaded_bytes",
    "artifact_count", "media_assets",
})


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
    parent_source_version: str

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.parent_page_id, self.filename, self.parent_source_version)):
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


def is_drawio_attachment_name(filename: object) -> bool:
    """Whether `filename` can name a draw.io diagram source.

    Confluence Data Center stores the diagram source with **no extension at
    all**: a page carrying "Untitled Diagram-1786592716372" also carries
    "Untitled Diagram-1786592716372.png" (the rendered preview) and
    "~Untitled Diagram-1786592716372.tmp" (an editor draft). An extension
    whitelist on its own therefore rejected every real diagram while happily
    admitting the preview, so no draw.io capture could ever complete.

    A name that does carry an extension still has to be one of the known ones,
    which keeps the preview and the drafts out.
    """
    if type(filename) is not str or not filename:
        return False
    if filename.lower().endswith((".drawio", ".drawio.xml", ".xml")):
        return True
    return "." not in filename


def match_drawio_attachment(reference: DrawioReference, attachments: Iterable[AttachmentMetadata]) -> AttachmentMetadata | None:
    """Return one parent/name/version match; ambiguity fails closed.

    Names are compared with surrounding whitespace stripped: Confluence stores a
    draw.io source attachment with a leading space (a page's macro references
    ``Relation`` while the stored source is ``" Relation"``), so an exact ``==``
    matched zero candidates and failed the whole capture. Stripping both sides
    fixes the space discrepancy; a genuine collision still trips the ambiguity
    guard below and fails closed.
    """
    if type(reference) is not DrawioReference:
        raise TypeError("reference is invalid")
    if type(attachments) not in (tuple, list):
        attachments = tuple(attachments)
    for item in attachments:
        if type(item) is not AttachmentMetadata:
            raise TypeError("attachment metadata is invalid")
    wanted = reference.filename.strip()
    candidates = tuple(a for a in attachments if type(a) is AttachmentMetadata and a.parent_page_id == reference.parent_page_id and a.filename.strip() == wanted and is_drawio_attachment_name(a.filename))
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


def capture_drawio_with_production_components(
    *,
    references: Iterable[DrawioReference],
    attachment_observer: object,
    body_materializer: object,
    media_processor: object,
    run_id: CrawlRunId,
    selection_identity: str,
    prior_state: Mapping[str, object] | None = None,
    persist_state: Callable[[Mapping[str, object]], object] | None = None,
    acknowledge: Callable[[str], object] | None = None,
    config: ConfluenceSubtreeCorpusConfig | None = None,
) -> dict[str, object]:
    """Compose the approved metadata, body, raw-store and media use cases.

    ``attachment_observer`` must expose ``list_attachments(page_id)`` and
    return ``ConfluenceAttachmentObservation`` values.  The materializer is
    the existing ``FetchAndStoreConfluenceAttachmentBody`` use case and the
    processor is ``ProcessConfluenceMediaAttachment``.  Only exact Draw.io
    matches are materialized; non-Draw.io metadata is never passed to the
    body fetcher.  Acknowledgement happens only after successful processing.
    """
    list_attachments = getattr(attachment_observer, "list_attachments", None)
    execute_body = getattr(body_materializer, "execute", None)
    execute_media = getattr(media_processor, "execute", None)
    from knowledgenexus.foundation.domain.models.media_materialization import (
        ConfluenceAttachmentObservation, MediaPolicyDecision,
    )
    if type(run_id) is not CrawlRunId:
        raise TypeError("run_id is invalid")
    try:
        run_id = CrawlRunId(run_id.value)
    except Exception:
        raise ValueError("run_id is invalid") from None
    if type(selection_identity) is not str or _SHA256.fullmatch(selection_identity) is None:
        raise ValueError("selection_identity is invalid")
    if persist_state is not None and not callable(persist_state):
        raise TypeError("persist_state is invalid")
    refs = tuple(sorted(tuple(references), key=_drawio_reference_key))
    if any(type(ref) is not DrawioReference for ref in refs):
        raise TypeError("drawio reference is invalid")
    if len({_drawio_reference_key(ref) for ref in refs}) != len(refs):
        raise ValueError("drawio references contain duplicates")
    if refs and (not callable(list_attachments) or not callable(execute_body) or not callable(execute_media)):
        raise TypeError("production attachment components are invalid")
    failures = 0
    observed = len(refs)
    cfg = config or ConfluenceSubtreeCorpusConfig(max_pages=MAX_PAGES)
    if observed > cfg.drawio_count:
        raise ValueError("drawio artifact budget exhausted")
    observed_keys = tuple(_drawio_reference_key(ref) for ref in refs)
    assets, resolutions, downloaded_bytes = validate_drawio_capture_state(
        prior_state,
        run_id=run_id,
        selection_identity=selection_identity,
        observed_keys=observed_keys,
        config=cfg,
    )
    resolved_keys = {tuple(entry["reference"]) for entry in resolutions}

    def snapshot() -> dict[str, object]:
        return {
            "format_version": _DRAWIO_STATE_FORMAT_VERSION,
            "run_id": str(run_id),
            "generation_id": str(run_id),
            "selection_identity": selection_identity,
            "observed": [list(key) for key in observed_keys],
            "resolutions": [dict(entry) for entry in resolutions],
            "failed": failures,
            "downloaded_bytes": downloaded_bytes,
            "artifact_count": len(resolutions),
            "media_assets": [dict(asset) for asset in assets],
        }

    for ref in refs:
        key = _drawio_reference_key(ref)
        if key in resolved_keys:
            continue
        observation = None
        try:
            metadata = tuple(list_attachments(ref.parent_page_id))
            # Compare names with surrounding whitespace stripped: Confluence
            # stores a draw.io source with a leading space (macro references
            # "Relation" while the stored source is " Relation"), so an exact
            # "==" matched zero candidates and failed the whole capture.
            wanted_filename = ref.filename.strip()
            candidates = tuple(
                item for item in metadata
                if type(item) is ConfluenceAttachmentObservation
                and item.parent_page_id == ref.parent_page_id
                and item.filename.strip() == wanted_filename
                and is_drawio_attachment_name(item.filename)
            )
            if len(candidates) != 1:
                # Not an exception, so this counted as a failure without ever
                # reaching the handler below -- the quietest of the paths that
                # produce "capture incomplete". Name what was wanted and what
                # the page actually carries, since a mismatch here is usually
                # a naming difference rather than a fetch problem.
                logger.error(
                    "Draw.io reference unmatched on page %s: wanted filename %r, "
                    "matched %d candidate(s) out of %d attachment(s); attachments seen: %s",
                    ref.parent_page_id, ref.filename, len(candidates), len(metadata),
                    [getattr(item, "filename", "?") for item in metadata][:20],
                )
                failures += 1
                continue
            observation = candidates[0]
            decision = MediaPolicyDecision(attachment_id=observation.attachment_id, policy="download_and_process")
            materialized = execute_body(observation=observation, decision=decision)
            envelope = getattr(materialized, "envelope", None)
            # Materializers return a typed result with the immutable artifact;
            # read the published body through the raw-store boundary.
            artifact = getattr(materialized, "artifact", None)
            if envelope is None:
                store = getattr(body_materializer, "raw_attachment_store", None)
                read = getattr(store, "read_attachment", None)
                if callable(read) and artifact is not None:
                    envelope = read(attachment_id=observation.attachment_id, content_hash=artifact.body_sha256)
            if envelope is None:
                raise ValueError("materializer did not expose envelope")
            processed = execute_media(envelope=envelope, observation=observation)
            artifact = getattr(materialized, "artifact", None)
            byte_count = getattr(artifact, "byte_count", None)
            if type(byte_count) is not int or byte_count < 0 or downloaded_bytes + byte_count > cfg.drawio_bytes:
                raise ValueError("drawio budget exhausted")
            downloaded_bytes += byte_count
            asset = dict(getattr(processed, "asset", {}))
            expected_parent_id = DocumentIdGenerator.confluence_page_id(ref.parent_page_id)
            if (
                not asset
                or asset.get("parent_document_id") != expected_parent_id
                # The asset carries the real attachment filename (e.g. the
                # leading-space " Relation"); compare stripped, consistent with
                # how the reference was matched above.
                or (asset.get("filename") or "").strip() != wanted_filename
                or type(asset.get("media_id")) is not str
            ):
                raise ValueError("media processor returned no asset")
            assets.append(asset)
            resolved_keys.add(key)
            resolutions.append({
                "reference": list(key),
                "media_id": asset["media_id"],
                "body_byte_count": byte_count,
            })
            assets.sort(key=lambda item: str(item.get("media_id", "")))
            resolutions.sort(key=lambda item: tuple(item["reference"]))
            if persist_state is not None:
                persist_state(snapshot())
            if acknowledge is not None:
                acknowledge(observation.attachment_id)
        except Exception:
            # Counting the failure and dropping the reason is why a draw.io
            # problem could only ever surface as "capture incomplete": the
            # count survives, the cause does not. Keep swallowing it so one
            # bad attachment cannot abort the whole capture, but say what
            # went wrong first.
            logger.exception(
                "Draw.io capture failed for page %s attachment %r; observation: %s",
                getattr(ref, "parent_page_id", "?"), getattr(ref, "filename", "?"),
                "not reached" if observation is None else (
                    f"attachment_id={observation.attachment_id!r} "
                    f"source_version={observation.source_version!r} "
                    f"mime_type={observation.mime_type!r} "
                    f"size_bytes={observation.size_bytes!r} "
                    f"updated_at={observation.updated_at!r}"
                ),
            )
            failures += 1
    final_state = snapshot()
    if persist_state is not None:
        persist_state(final_state)
    return {
        "media_assets": tuple(assets),
        "drawio_references_observed": observed,
        "drawio_references_resolved": len(resolved_keys),
        "drawio_assets_failed": failures,
        "state": final_state,
    }


def _drawio_reference_key(reference: DrawioReference) -> tuple[str, str, str]:
    if type(reference) is not DrawioReference:
        raise TypeError("drawio reference is invalid")
    return (
        reference.parent_page_id,
        reference.filename,
        reference.parent_source_version,
    )


def validate_drawio_capture_state(
    value: Mapping[str, object] | None,
    *,
    run_id: CrawlRunId,
    selection_identity: str,
    observed_keys: tuple[tuple[str, str, str], ...],
    config: ConfluenceSubtreeCorpusConfig,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    if value is None:
        return [], [], 0
    if not isinstance(value, Mapping):
        raise TypeError("drawio state is invalid")
    state = dict(value)
    if frozenset(state) != _DRAWIO_STATE_FIELDS:
        raise ValueError("drawio state is invalid")
    if (
        state["format_version"] != _DRAWIO_STATE_FORMAT_VERSION
        or state["run_id"] != str(run_id)
        or state["generation_id"] != str(run_id)
        or state["selection_identity"] != selection_identity
        or state["observed"] != [list(key) for key in observed_keys]
    ):
        raise ValueError("drawio state binding mismatch")
    if (
        type(state["failed"]) is not int
        or state["failed"] < 0
        or type(state["downloaded_bytes"]) is not int
        or state["downloaded_bytes"] < 0
        or type(state["artifact_count"]) is not int
        or state["artifact_count"] < 0
        or type(state["resolutions"]) is not list
        or type(state["media_assets"]) is not list
    ):
        raise ValueError("drawio state is invalid")
    resolutions: list[dict[str, object]] = []
    resolution_keys: set[tuple[str, str, str]] = set()
    media_ids: set[str] = set()
    byte_total = 0
    for raw in state["resolutions"]:
        if type(raw) is not dict or set(raw) != {"reference", "media_id", "body_byte_count"}:
            raise ValueError("drawio resolution is invalid")
        reference = raw["reference"]
        media_id = raw["media_id"]
        byte_count = raw["body_byte_count"]
        if (
            type(reference) is not list
            or len(reference) != 3
            or any(type(part) is not str or not part for part in reference)
            or type(media_id) is not str
            or not media_id
            or type(byte_count) is not int
            or byte_count < 0
        ):
            raise ValueError("drawio resolution is invalid")
        key = tuple(reference)
        if key not in observed_keys or key in resolution_keys or media_id in media_ids:
            raise ValueError("drawio resolution binding is invalid")
        resolution_keys.add(key)
        media_ids.add(media_id)
        byte_total += byte_count
        resolutions.append({"reference": list(key), "media_id": media_id, "body_byte_count": byte_count})
    assets = [dict(asset) for asset in state["media_assets"] if type(asset) is dict]
    if len(assets) != len(state["media_assets"]) or len(assets) != len(resolutions):
        raise ValueError("drawio media assets are invalid")
    assets_by_id = {asset.get("media_id"): asset for asset in assets}
    if len(assets_by_id) != len(assets) or set(assets_by_id) != media_ids:
        raise ValueError("drawio media asset binding is invalid")
    for resolution in resolutions:
        parent_page_id, filename, _ = resolution["reference"]
        asset = assets_by_id[resolution["media_id"]]
        if (
            asset.get("parent_document_id") != DocumentIdGenerator.confluence_page_id(parent_page_id)
            # The asset keeps the real attachment filename (e.g. the
            # leading-space " Relation") while the reference key uses the
            # trimmed macro name; compare stripped, as elsewhere in this module.
            or (asset.get("filename") or "").strip() != filename.strip()
        ):
            raise ValueError("drawio media asset binding is invalid")
    if (
        state["artifact_count"] != len(resolutions)
        or state["downloaded_bytes"] != byte_total
        or len(resolutions) > config.drawio_count
        or byte_total > config.drawio_bytes
    ):
        raise ValueError("drawio state budget is invalid")
    assets.sort(key=lambda item: str(item.get("media_id", "")))
    resolutions.sort(key=lambda item: tuple(item["reference"]))
    return assets, resolutions, byte_total


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


__all__ = ["AttachmentMetadata", "ConfluenceSubtreeCorpusConfig", "ConfluenceSubtreeCorpusHarness", "DrawioReference", "SubtreePacketExporter", "capture_drawio_assets", "capture_drawio_with_production_components", "match_drawio_attachment", "partition_page_ids", "process_preserved_pages", "validate_drawio_capture_state", "PACKET_FORMAT_VERSION"]
