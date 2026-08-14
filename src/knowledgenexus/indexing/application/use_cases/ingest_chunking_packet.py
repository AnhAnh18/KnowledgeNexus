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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.ports.embedder_port import EmbedderPort
from knowledgenexus.indexing.application.use_cases.chunk_storage_service import ChunkStorageService
from knowledgenexus.shared.errors import StorageError

logger = logging.getLogger(__name__)

_CHUNKS_FILE = "chunks.jsonl"
_DOCUMENTS_FILE = "documents.jsonl"

# Foundation chunk_id/document_id values (e.g. "chunk:confluence:<hash>",
# "confluence:page:<id>") are not valid UUIDs, but CoreChunkMetadata.document_id
# and Qdrant/SQLite point ids must be. Derive stable UUID5s from the original
# ids so ingestion is deterministic and idempotent, while the original ids are
# preserved in ChunkPayload.extra for traceability.
_CHUNK_ID_NAMESPACE = uuid5(NAMESPACE_URL, "knowledgenexus.indexing.chunk_id")
_DOCUMENT_ID_NAMESPACE = uuid5(NAMESPACE_URL, "knowledgenexus.indexing.document_id")


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

    async def execute(self, packet_path: Path) -> IngestionResult:
        """Execute packet ingestion.

        Args:
            packet_path: Path to Foundation packet directory

        Returns:
            IngestionResult with ingestion metrics

        Raises:
            PacketFormatError: If packet structure is invalid
            ChunkTransformationError: If chunk transformation fails
            StorageError: If storage operations fail
        """
        packet_path = Path(packet_path)
        self._validate_packet_structure(packet_path)

        # Load and parse documents (for source_id mapping)
        documents = self._load_documents(packet_path / _DOCUMENTS_FILE)

        # Load chunks
        chunk_records = self._load_chunks(packet_path / _CHUNKS_FILE)
        logger.info("Loaded %d chunk records from packet", len(chunk_records))

        return await self.execute_records(chunk_records, documents)

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

    def _validate_packet_structure(self, packet_path: Path) -> None:
        """Validate packet directory structure."""
        if not packet_path.is_dir():
            raise PacketFormatError(f"Packet path is not a directory: {packet_path}")

        chunks_file = packet_path / _CHUNKS_FILE
        if not chunks_file.is_file():
            raise PacketFormatError(f"Missing {_CHUNKS_FILE} in packet")

        logger.info("Packet structure validated: %s", packet_path)

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
                        logger.warning(
                            "Failed to parse document at line %d: %s",
                            line_num,
                            exc,
                        )
            logger.info("Loaded %d documents from packet", len(documents))
        except Exception as exc:
            logger.warning("Error loading documents file: %s", exc)

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
                        logger.warning(
                            "Failed to parse chunk at line %d: %s",
                            line_num,
                            exc,
                        )
        except Exception as exc:
            raise PacketFormatError(f"Error reading chunks file: {exc}") from exc

        return chunks

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
            url=None,  # Will be populated by retrieval layer if needed
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
