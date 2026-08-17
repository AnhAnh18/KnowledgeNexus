"""Ingest a Foundation chunking packet into Qdrant vector store.

This use case bridges Foundation (chunking) and Indexing (storage) layers:
1. Read chunks.jsonl from Foundation packet
2. Transform ChunkRecord (dict) → Chunk (domain model)
3. Embed chunks (dense + sparse vectors)
4. Store in SQLite + Qdrant
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort
from knowledgenexus.indexing.application.use_cases.chunk_storage_service import ChunkStorageService
from knowledgenexus.shared.errors import StorageError
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain, require_plain_file

logger = logging.getLogger(__name__)

_CHUNKS_FILE = "chunks.jsonl"
_DOCUMENTS_FILE = "documents.jsonl"
_MEDIA_FILE = "media_assets.jsonl"
_SUMMARY_FILE = "packet_summary.json"
_PACKET_FILES = frozenset({_CHUNKS_FILE, _DOCUMENTS_FILE, _MEDIA_FILE, _SUMMARY_FILE})
_PACKET_FORMAT = "confluence-subtree-indexing-packet-v1"

# Foundation chunk_id/document_id values (e.g. "chunk:confluence:<hash>",
# "confluence:page:<id>") are not valid UUIDs, but CoreChunkMetadata.document_id
# and Qdrant/SQLite point ids must be. Derive stable UUID5s from the original
# ids so ingestion is deterministic and idempotent, while the original ids are
# preserved in ChunkPayload.extra for traceability.
_CHUNK_ID_NAMESPACE = uuid5(NAMESPACE_URL, "knowledgenexus.indexing.chunk_id")
_DOCUMENT_ID_NAMESPACE = uuid5(NAMESPACE_URL, "knowledgenexus.indexing.document_id")

# How often embedding progress is reported, in chunks.
_EMBED_PROGRESS_EVERY = 25

# Called as ``await report(embedded_chunks=..., total_chunks=...)``.
EmbedProgressReporter = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class IngestionResult:
    """Result of packet ingestion."""
    chunks_ingested: int
    chunks_failed: int
    source_id: str
    embedding_model: str
    status: str  # "success" | "partial" | "failed"


class ChunkingPacketError(Exception):
    """Base error for packet ingestion."""
    pass


class PacketFormatError(ChunkingPacketError):
    """Raised when packet format is invalid."""
    pass


class ChunkTransformationError(ChunkingPacketError):
    """Raised when chunk transformation fails."""
    pass


class IngestChunkingPacket:
    """Ingest Foundation chunking packet into Qdrant.

    Expects packet structure:
        packet/
        ├── documents.jsonl  (unused for now, but validates metadata)
        ├── chunks.jsonl     (source of truth for ingestion)
        └── packet_summary.json
    """

    def __init__(
        self,
        embedder: EmbedderPort,
        chunk_storage_service: ChunkStorageService,
    ) -> None:
        if not hasattr(embedder, "embed"):
            raise TypeError("embedder must implement EmbedderPort")
        if not hasattr(chunk_storage_service, "save"):
            raise TypeError("chunk_storage_service must implement ChunkStorageService")

        self._embedder = embedder
        self._storage_service = chunk_storage_service

    async def execute(
        self, packet_path: Path, report_progress: EmbedProgressReporter | None = None
    ) -> IngestionResult:
        """Execute packet ingestion.

        Args:
            packet_path: Path to Foundation packet directory
            report_progress: Optional async callback invoked periodically while
                chunks are embedded, as ``report(embedded_chunks=, total_chunks=)``.

        Returns:
            IngestionResult with ingestion metrics

        Raises:
            PacketFormatError: If packet structure is invalid
            ChunkTransformationError: If chunk transformation fails
            StorageError: If storage operations fail
        """
        packet_path = Path(packet_path)
        summary = self._validate_packet_structure(packet_path)
        documents = self._load_documents(packet_path / _DOCUMENTS_FILE)
        chunk_records = self._load_chunks(packet_path / _CHUNKS_FILE)
        media_assets = self._load_media_assets(packet_path / _MEDIA_FILE)
        self._validate_published_packet(summary, documents, chunk_records, media_assets)
        logger.info("Loaded %d chunk records from packet", len(chunk_records))
        return await self._execute_records_strict(chunk_records, documents, report_progress)

    async def execute_records(
        self,
        chunk_records: list[dict[str, Any]],
        documents: list[dict[str, Any]] | None = None,
    ) -> IngestionResult:
        """Execute ingestion directly from in-memory ChunkRecord dicts.

        Same transform → embed → store pipeline as `execute()`, but takes
        records already held in memory (e.g. `ChunkingResult.records` from
        Foundation's `BuildConfluenceChunks`) instead of reading a packet
        directory from disk.

        Args:
            chunk_records: Raw ChunkRecord dicts from Foundation.
            documents: Optional document metadata dicts, used for
                source_id mapping.

        Returns:
            IngestionResult with ingestion metrics

        Raises:
            StorageError: If storage operations fail
        """
        doc_by_id = {doc.get("document_id"): doc for doc in documents or []}

        if not chunk_records:
            return IngestionResult(
                chunks_ingested=0,
                chunks_failed=0,
                source_id="",
                embedding_model=self._embedder.model_name,
                status="success",
            )

        # Transform and embed chunks
        chunks_to_save: list[Chunk] = []
        failed_count = 0
        source_ids: set[str] = set()

        for chunk_record in chunk_records:
            try:
                chunk = await self._transform_and_embed_chunk(
                    chunk_record,
                    document=doc_by_id.get(chunk_record.get("document_id")),
                )
                chunks_to_save.append(chunk)
                source_ids.add(chunk.payload.core.source_id)
            except Exception as exc:
                logger.warning(
                    "Failed to ingest chunk %s: %s",
                    chunk_record.get("chunk_id"),
                    exc,
                )
                failed_count += 1

        if not chunks_to_save:
            return IngestionResult(
                chunks_ingested=0,
                chunks_failed=failed_count,
                source_id=list(source_ids)[0] if source_ids else "",
                embedding_model=self._embedder.model_name,
                status="failed",
            )

        # Save to storage
        try:
            await self._storage_service.save(chunks_to_save)
            logger.info("Successfully saved %d chunks to storage", len(chunks_to_save))
        except Exception as exc:
            logger.error("Failed to save chunks to storage: %s", exc)
            raise StorageError(f"Failed to save chunks: {exc}") from exc

        status = "success" if failed_count == 0 else "partial"
        source_id = list(source_ids)[0] if source_ids else ""

        return IngestionResult(
            chunks_ingested=len(chunks_to_save),
            chunks_failed=failed_count,
            source_id=source_id,
            embedding_model=self._embedder.model_name,
            status=status,
        )

    def _validate_packet_structure(self, packet_path: Path) -> dict[str, Any]:
        """Validate packet directory structure."""
        if not packet_path.is_dir() or packet_path.is_symlink():
            raise PacketFormatError(f"Packet path is not a directory: {packet_path}")
        try:
            require_plain_directory_chain(packet_path)
        except Exception as exc:
            raise PacketFormatError("Packet path is unsafe") from exc
        names = {path.name for path in packet_path.iterdir()}
        if names != _PACKET_FILES:
            raise PacketFormatError("Packet file set is invalid")
        for name in _PACKET_FILES:
            path = packet_path / name
            try:
                require_plain_file(path)
            except Exception as exc:
                raise PacketFormatError("Packet artifact is unsafe") from exc
        try:
            summary = json.loads((packet_path / _SUMMARY_FILE).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PacketFormatError("Packet completion marker is invalid") from exc
        if type(summary) is not dict:
            raise PacketFormatError("Packet completion marker is invalid")

        logger.info("Packet structure validated: %s", packet_path)
        return summary

    def _load_documents(self, documents_file: Path) -> list[dict[str, Any]]:
        """Load documents from JSONL file."""
        documents: list[dict[str, Any]] = []
        if not documents_file.exists():
            logger.warning("Documents file not found: %s", documents_file)
            return documents

        try:
            with open(documents_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    if not line.strip():
                        continue
                    try:
                        doc = json.loads(line)
                        documents.append(doc)
                    except json.JSONDecodeError as exc:
                        raise PacketFormatError(f"Invalid document JSONL at line {line_num}") from exc
            logger.info("Loaded %d documents from packet", len(documents))
        except PacketFormatError:
            raise
        except Exception as exc:
            raise PacketFormatError("Error reading documents file") from exc

        return documents

    def _load_chunks(self, chunks_file: Path) -> list[dict[str, Any]]:
        """Load chunk records from JSONL file."""
        if not chunks_file.is_file():
            raise PacketFormatError(f"Chunks file not found: {chunks_file}")

        chunks: list[dict[str, Any]] = []
        try:
            with open(chunks_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        chunks.append(chunk)
                    except json.JSONDecodeError as exc:
                        raise PacketFormatError(f"Invalid chunk JSONL at line {line_num}") from exc
        except PacketFormatError:
            raise
        except Exception as exc:
            raise PacketFormatError("Error reading chunks file") from exc

        return chunks

    def _load_media_assets(self, media_file: Path) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        try:
            with open(media_file, "r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PacketFormatError(
                            f"Invalid media JSONL at line {line_number}"
                        ) from exc
                    if type(row) is not dict:
                        raise PacketFormatError("Media record is invalid")
                    assets.append(row)
        except PacketFormatError:
            raise
        except Exception as exc:
            raise PacketFormatError("Error reading media assets file") from exc
        return assets

    def _validate_published_packet(
        self, summary: dict[str, Any], documents: list[dict[str, Any]],
        chunks: list[dict[str, Any]], media_assets: list[dict[str, Any]],
    ) -> None:
        if (
            summary.get("format_version") != _PACKET_FORMAT
            or summary.get("acl_mode") != "restricted_unresolved"
            or summary.get("processing_status", "complete") != "complete"
            or summary.get("document_count") != len(documents)
            or summary.get("chunk_count") != len(chunks)
            or summary.get("media_asset_count") != len(media_assets)
        ):
            raise PacketFormatError("Packet summary is inconsistent or not strict-complete")
        validator = FoundationSchemaValidator()
        document_ids: set[str] = set()
        try:
            for document in documents:
                validator.validate_record("CanonicalDocument", document)
                document_id = document.get("document_id")
                if type(document_id) is not str or document_id in document_ids:
                    raise PacketFormatError("Document closure is invalid")
                document_ids.add(document_id)
            chunk_ids: set[str] = set()
            for chunk in chunks:
                validator.validate_record("ChunkRecord", chunk)
                chunk_id = chunk.get("chunk_id")
                if (
                    type(chunk_id) is not str
                    or chunk_id in chunk_ids
                    or chunk.get("document_id") not in document_ids
                    or chunk.get("acl_tags") != ["restricted:unresolved"]
                ):
                    raise PacketFormatError("Chunk closure is invalid")
                chunk_ids.add(chunk_id)
            media_ids: set[str] = set()
            for asset in media_assets:
                validator.validate_record("MediaAsset", asset)
                media_id = asset.get("media_id")
                if (
                    type(media_id) is not str or media_id in media_ids
                    or asset.get("parent_document_id") not in document_ids
                ):
                    raise PacketFormatError("Media closure is invalid")
                media_ids.add(media_id)
        except PacketFormatError:
            raise
        except Exception as exc:
            raise PacketFormatError("Packet schema validation failed") from exc

    async def _execute_records_strict(
        self,
        chunk_records: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        report_progress: EmbedProgressReporter | None = None,
    ) -> IngestionResult:
        # Same validity rule as `_to_documents`, so the lookup and the rows
        # written agree on which records count. A bare `document["document_id"]`
        # here raised KeyError on any record missing the field.
        doc_by_id = {
            document["document_id"]: document
            for document in documents
            if isinstance(document.get("document_id"), str) and document["document_id"]
        }
        chunks: list[Chunk] = []
        source_ids: set[str] = set()
        total = len(chunk_records)
        for position, record in enumerate(chunk_records, start=1):
            try:
                chunk = await self._transform_and_embed_chunk(record, document=doc_by_id[record["document_id"]])
            except Exception as exc:
                raise ChunkTransformationError("Strict packet transformation failed") from exc
            chunks.append(chunk)
            source_ids.add(chunk.payload.core.source_id)
            # Embedding every chunk is the longest stretch of the whole job and
            # used to report nothing at all. Throttle so a large packet does not
            # turn one job-status row into thousands of writes.
            if report_progress is not None and (
                position == total or position % _EMBED_PROGRESS_EVERY == 0
            ):
                await report_progress(embedded_chunks=position, total_chunks=total)
        try:
            await self._storage_service.save_documents_and_chunks(
                self._to_documents(documents), chunks
            )
        except Exception as exc:
            raise StorageError("Strict packet storage failed") from exc
        return IngestionResult(
            chunks_ingested=len(chunks), chunks_failed=0,
            source_id=",".join(sorted(source_ids)),
            embedding_model=self._embedder.model_name, status="success",
        )

    @staticmethod
    def _to_documents(documents: list[dict[str, Any]]) -> list[Document]:
        """Map packet document records onto the domain model.

        `source_id` follows the same rule `_transform_and_embed_chunk` uses for
        chunks, so a document and its chunks agree on what they belong to. The
        id is a stable UUID5 of the Foundation document_id, and the repository
        upserts on (source_type, source_id), so re-ingesting a subtree updates
        rows instead of duplicating them.
        """
        mapped: list[Document] = []
        for record in documents:
            document_id = record.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                continue
            page_id, space_key = record.get("page_id"), record.get("space_key")
            source_id = str(page_id) if page_id else str(space_key or document_id)
            metadata = record.get("metadata")
            mapped.append(Document(
                id=uuid5(_DOCUMENT_ID_NAMESPACE, document_id),
                title=str(record.get("title") or document_id),
                # The documents table has no content column -- the text lives in
                # the chunks -- so nothing is lost by not rebuilding it here.
                content="",
                source_type=SourceType.CONFLUENCE,
                source_id=source_id,
                url=record.get("url") if isinstance(record.get("url"), str) else None,
                metadata={
                    **(metadata if isinstance(metadata, dict) else {}),
                    "foundation_document_id": document_id,
                    **({"space_key": space_key} if isinstance(space_key, str) else {}),
                    **({"page_id": str(page_id)} if page_id else {}),
                },
            ))
        return mapped

    async def _transform_and_embed_chunk(
        self,
        chunk_record: dict[str, Any],
        document: dict[str, Any] | None = None,
    ) -> Chunk:
        """Transform ChunkRecord to Chunk and embed.

        Args:
            chunk_record: Raw chunk record from Foundation (dict)
            document: Optional document metadata

        Returns:
            Chunk with embedding vectors
        """
        # Validate required fields
        chunk_id = chunk_record.get("chunk_id")
        document_id = chunk_record.get("document_id")
        text = chunk_record.get("text")

        if not chunk_id or not isinstance(chunk_id, str):
            raise ChunkTransformationError("Missing or invalid chunk_id")
        if not document_id or not isinstance(document_id, str):
            raise ChunkTransformationError("Missing or invalid document_id")
        if not text or not isinstance(text, str):
            raise ChunkTransformationError("Missing or invalid text")

        # Extract metadata from chunk record
        source_system = chunk_record.get("source_system", "confluence")
        source_type_str = chunk_record.get("source_type", "wiki_page")
        title = chunk_record.get("title", "")
        heading_path = chunk_record.get("heading_path", [])
        content_kind = chunk_record.get("content_kind", "prose")
        language = chunk_record.get("language", "unknown")
        space_key = chunk_record.get("space_key")
        page_id = chunk_record.get("page_id")
        chunk_index = chunk_record.get("chunk_index", 0)
        part_index = chunk_record.get("part_index")
        part_total = chunk_record.get("part_total")

        # Map source type
        try:
            if source_type_str == "wiki_page":
                source_type = SourceType.CONFLUENCE
            else:
                source_type = SourceType.CONFLUENCE  # default for now
        except ValueError as exc:
            raise ChunkTransformationError(f"Invalid source_type: {source_type_str}") from exc

        # Generate source_id (use page_id if available, else space_key)
        source_id = str(page_id) if page_id else str(space_key or document_id)

        # Embed chunk text
        embedding_vectors = await self._embedder.embed([text])
        if not embedding_vectors:
            raise ChunkTransformationError(f"Failed to embed chunk {chunk_id}")

        embedding = embedding_vectors[0]

        # Build core metadata (document_id isn't a UUID either — e.g.
        # "confluence:page:1000" — so derive one the same way as chunk_id)
        core = CoreChunkMetadata(
            document_id=uuid5(_DOCUMENT_ID_NAMESPACE, document_id),
            source_type=source_type,
            source_id=source_id,
            title=title,
            # Retrieval hydrates chunks (rather than documents) before it
            # builds citations, so the page URL must be present on the chunk.
            url=(
                document.get("url")
                if isinstance(document, dict)
                and isinstance(document.get("url"), str)
                else None
            ),
            chunk_index=chunk_index,
            total_chunks=1,  # Set by retrieval layer
            indexed_at=datetime.utcnow(),
            embedding_model=self._embedder.model_name,
        )

        # Build extra metadata
        extra: dict[str, object] = {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "source_system": source_system,
            "content_kind": content_kind,
            "language": language,
            "heading_path": heading_path,
            "acl_tags": chunk_record.get("acl_tags"),
        }
        if space_key is not None:
            extra["space_key"] = space_key
        if page_id is not None:
            extra["page_id"] = page_id
        if part_index is not None:
            extra["part_index"] = part_index
        if part_total is not None:
            extra["part_total"] = part_total

        # Build chunk (Qdrant/SQLite require a UUID id; the original
        # Foundation chunk_id is preserved in extra["chunk_id"] above)
        chunk = Chunk(
            id=str(uuid5(_CHUNK_ID_NAMESPACE, chunk_id)),
            payload=ChunkPayload(
                core=core,
                content=text,
                extra=extra,
            ),
            dense_vector=embedding.values,
            sparse_vector=embedding.sparse,
        )

        logger.debug("Transformed and embedded chunk: %s", chunk_id)
        return chunk
