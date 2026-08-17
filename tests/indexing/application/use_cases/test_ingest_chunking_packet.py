"""Tests for IngestChunkingPacket use case."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest

from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    IngestChunkingPacket,
    IngestionResult,
    PacketFormatError,
    ChunkTransformationError,
    _CHUNK_ID_NAMESPACE,
    _DOCUMENT_ID_NAMESPACE,
)
from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector, SparseVector


class _MockEmbedder:
    """Mock embedder for testing."""

    def __init__(self, return_sparse: bool = False):
        self._return_sparse = return_sparse
        self.embedded_texts: list[str] = []

    @property
    def model_name(self) -> str:
        return "test-embedder"

    @property
    def dimension(self) -> int:
        return 768

    @property
    def supports_sparse(self) -> bool:
        return self._return_sparse

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        self.embedded_texts.extend(texts)
        results = []
        for text in texts:
            dense = [0.1] * self.dimension
            sparse = (
                SparseVector(indices=[1, 2, 3], values=[0.5, 0.3, 0.2])
                if self._return_sparse
                else None
            )
            results.append(
                EmbeddingVector(
                    values=dense,
                    model_name=self.model_name,
                    dimension=self.dimension,
                    sparse=sparse,
                )
            )
        return results

    async def embed_query(self, query: str) -> EmbeddingVector:
        dense = [0.1] * self.dimension
        sparse = (
            SparseVector(indices=[1, 2], values=[0.6, 0.4])
            if self._return_sparse
            else None
        )
        return EmbeddingVector(
            values=dense,
            model_name=self.model_name,
            dimension=self.dimension,
            sparse=sparse,
        )


class _MockChunkStorageService:
    """Mock storage service for testing."""

    def __init__(self):
        self.saved_chunks: list[Chunk] = []
        self.saved_documents: list = []

    async def save(self, chunks: list[Chunk]) -> None:
        self.saved_chunks.extend(chunks)

    async def save_document_and_chunks(self, document, chunks):
        self.saved_documents.append(document)
        self.saved_chunks.extend(chunks)

    async def save_documents_and_chunks(self, documents, chunks):
        self.saved_documents.extend(documents)
        self.saved_chunks.extend(chunks)

    async def search(self, dense_vector, top_k, filters=None):
        return []

    async def get_by_ids(self, chunk_ids):
        return []

    async def delete_by_source_id(self, source_type, source_id):
        pass

    async def delete_by_document_id(self, document_id):
        pass

    async def get_stats(self):
        return {}


@pytest.fixture
def mock_embedder():
    return _MockEmbedder(return_sparse=False)


@pytest.fixture
def mock_storage_service():
    return _MockChunkStorageService()


@pytest.fixture
def temp_packet_dir():
    """Create a temporary packet directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


class TestIngestChunkingPacketValidation:
    """Test packet validation."""

    async def test_missing_packet_directory(self, mock_embedder, mock_storage_service):
        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        with pytest.raises(PacketFormatError, match="not a directory"):
            await use_case.execute(Path("/nonexistent/packet"))

    async def test_missing_chunks_file(self, temp_packet_dir, mock_embedder, mock_storage_service):
        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        with pytest.raises(PacketFormatError, match="file set"):
            await use_case.execute(temp_packet_dir)

    async def test_empty_chunks_file(self, temp_packet_dir, mock_embedder, mock_storage_service):
        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        with pytest.raises(PacketFormatError, match="file set"):
            await use_case.execute(temp_packet_dir)


class TestIngestChunkingPacketTransformation:
    """Test chunk transformation."""

    async def test_ingest_single_chunk(self, temp_packet_dir, mock_embedder, mock_storage_service):
        doc_id = str(uuid4())
        chunk_id = "chunk-1"

        chunk_record = {
            "chunk_id": chunk_id,
            "document_id": doc_id,
            "text": "This is test content",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Test Page",
            "heading_path": ["Section", "Subsection"],
            "content_kind": "prose",
            "language": "en",
            "token_count": 4,
            "space_key": "TEST",
            "page_id": "12345",
            "acl_tags": ["restricted:unresolved"],
        }

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record], [{"document_id": doc_id, "title": "Test Page"}])

        assert result.chunks_ingested == 1
        assert result.chunks_failed == 0
        assert result.status == "success"
        assert result.embedding_model == "test-embedder"
        assert result.source_id == "12345"  # page_id

        # Verify chunk was embedded and stored
        assert len(mock_storage_service.saved_chunks) == 1
        saved_chunk = mock_storage_service.saved_chunks[0]
        # chunk_id isn't a UUID (Foundation format), so a deterministic UUID5
        # derived from it is used as the Qdrant/SQLite id instead.
        assert saved_chunk.id == str(uuid5(_CHUNK_ID_NAMESPACE, chunk_id))
        assert UUID(saved_chunk.id)  # must be a valid UUID
        assert saved_chunk.payload.extra["chunk_id"] == chunk_id
        assert saved_chunk.content == "This is test content"
        assert saved_chunk.dense_vector is not None
        assert len(saved_chunk.dense_vector) == 768

    async def test_ingest_multiple_chunks(self, temp_packet_dir, mock_embedder, mock_storage_service):
        doc_id = str(uuid4())
        chunks = [
            {
                "chunk_id": f"chunk-{i}",
                "document_id": doc_id,
                "text": f"Content {i}",
                "source_system": "confluence",
                "source_type": "wiki_page",
                "title": "Test",
                "heading_path": ["Section"],
                "content_kind": "prose",
                "language": "unknown",
                "page_id": "999",
            }
            for i in range(5)
        ]

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records(chunks)

        assert result.chunks_ingested == 5
        assert result.chunks_failed == 0
        assert result.status == "success"
        assert len(mock_storage_service.saved_chunks) == 5

        # Verify embedder was called for all texts
        assert len(mock_embedder.embedded_texts) == 5

    async def test_missing_required_field(self, temp_packet_dir, mock_embedder, mock_storage_service):
        chunk_record = {
            "chunk_id": "chunk-1",
            # Missing document_id
            "text": "Content",
        }

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record])

        assert result.chunks_ingested == 0
        assert result.chunks_failed == 1
        assert result.status == "failed"

    async def test_partial_failure(self, temp_packet_dir, mock_embedder, mock_storage_service):
        doc_id = str(uuid4())
        chunks = [
            {
                "chunk_id": "chunk-1",
                "document_id": doc_id,
                "text": "Valid content",
                "source_system": "confluence",
                "source_type": "wiki_page",
                "title": "Test",
                "heading_path": ["Section"],
                "content_kind": "prose",
                "language": "unknown",
                "page_id": "123",
            },
            {
                "chunk_id": "chunk-2",
                # Missing document_id
                "text": "Invalid content",
            },
            {
                "chunk_id": "chunk-3",
                "document_id": doc_id,
                "text": "Another valid",
                "source_system": "confluence",
                "source_type": "wiki_page",
                "title": "Test",
                "heading_path": ["Section"],
                "content_kind": "prose",
                "language": "unknown",
                "page_id": "123",
            },
        ]

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records(chunks)

        assert result.chunks_ingested == 2
        assert result.chunks_failed == 1
        assert result.status == "partial"

    async def test_sparse_vectors_when_supported(self, temp_packet_dir, mock_storage_service):
        embedder = _MockEmbedder(return_sparse=True)
        doc_id = str(uuid4())
        chunk_record = {
            "chunk_id": "chunk-1",
            "document_id": doc_id,
            "text": "Sparse test",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Test",
            "heading_path": ["Section"],
            "content_kind": "prose",
            "language": "unknown",
            "page_id": "456",
        }

        use_case = IngestChunkingPacket(embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record])

        assert result.chunks_ingested == 1
        saved_chunk = mock_storage_service.saved_chunks[0]
        assert saved_chunk.sparse_vector is not None
        assert len(saved_chunk.sparse_vector.indices) > 0

    async def test_metadata_mapping(self, temp_packet_dir, mock_embedder, mock_storage_service):
        doc_id = str(uuid4())
        chunk_record = {
            "chunk_id": "test-chunk-id",
            "document_id": doc_id,
            "text": "Test metadata",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Page Title",
            "heading_path": ["Section", "Subsection", "SubSubsection"],
            "content_kind": "code_block",
            "language": "python",
            "space_key": "MY_SPACE",
            "page_id": "98765",
            "part_index": 2,
            "part_total": 5,
        }

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record])

        assert result.chunks_ingested == 1
        saved_chunk = mock_storage_service.saved_chunks[0]
        core = saved_chunk.payload.core
        extra = saved_chunk.payload.extra

        # Verify core metadata (document_id isn't a UUID either in real
        # Foundation records, so it's mapped the same way as chunk_id)
        assert core.document_id == uuid5(_DOCUMENT_ID_NAMESPACE, doc_id)
        assert core.source_type == SourceType.CONFLUENCE
        assert core.source_id == "98765"
        assert core.title == "Page Title"

        # Verify extra metadata
        assert extra["chunk_id"] == "test-chunk-id"
        assert extra["document_id"] == doc_id
        assert extra["source_system"] == "confluence"
        assert extra["content_kind"] == "code_block"
        assert extra["language"] == "python"
        assert extra["heading_path"] == ["Section", "Subsection", "SubSubsection"]
        assert extra["space_key"] == "MY_SPACE"
        assert extra["page_id"] == "98765"
        assert extra["part_index"] == 2
        assert extra["part_total"] == 5

    async def test_non_uuid_chunk_id_maps_to_valid_uuid(
        self, mock_embedder, mock_storage_service
    ):
        """Foundation chunk_ids like 'chunk:confluence:<hash>' aren't UUIDs,
        but Qdrant/SQLite point ids must be valid UUIDs."""
        doc_id = str(uuid4())
        chunk_id = "chunk:confluence:9f3a1b2c4d5e6f70"
        chunk_record = {
            "chunk_id": chunk_id,
            "document_id": doc_id,
            "text": "Foundation-shaped chunk id",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Test",
            "heading_path": ["Section"],
            "content_kind": "prose",
            "language": "unknown",
            "page_id": "111",
        }

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record])

        assert result.chunks_ingested == 1
        saved_chunk = mock_storage_service.saved_chunks[0]
        assert UUID(saved_chunk.id) == uuid5(_CHUNK_ID_NAMESPACE, chunk_id)
        assert saved_chunk.payload.extra["chunk_id"] == chunk_id


class TestIngestChunkingPacketExecuteRecords:
    """Test execute_records() directly against in-memory ChunkRecord dicts."""

    async def test_ingest_in_memory_records(self, mock_embedder, mock_storage_service):
        doc_id = str(uuid4())
        chunk_records = [
            {
                "chunk_id": f"chunk-{i}",
                "document_id": doc_id,
                "text": f"Content {i}",
                "source_system": "confluence",
                "source_type": "wiki_page",
                "title": "Test",
                "heading_path": ["Section"],
                "content_kind": "prose",
                "language": "unknown",
                "page_id": "222",
            }
            for i in range(3)
        ]

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records(
            chunk_records, [{"document_id": doc_id, "title": "Test"}]
        )

        assert result.chunks_ingested == 3
        assert result.chunks_failed == 0
        assert result.status == "success"
        assert len(mock_storage_service.saved_chunks) == 3

    async def test_empty_records_list(self, mock_embedder, mock_storage_service):
        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([])

        assert result.chunks_ingested == 0
        assert result.chunks_failed == 0
        assert result.status == "success"

    async def test_no_documents_argument(self, mock_embedder, mock_storage_service):
        """documents is optional; source_id mapping still works via page_id."""
        chunk_record = {
            "chunk_id": "chunk-1",
            "document_id": str(uuid4()),
            "text": "No documents passed",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Test",
            "heading_path": ["Section"],
            "content_kind": "prose",
            "language": "unknown",
            "page_id": "333",
        }

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        result = await use_case.execute_records([chunk_record])

        assert result.chunks_ingested == 1
        assert result.source_id == "333"


class TestPacketDocumentsAndEmbedProgress:
    """The packet path must persist documents and report embedding progress.

    Both were silently missing: `_execute_records_strict` called `save()`,
    which drops document records entirely, and embedding -- the longest part
    of a subtree ingest -- reported nothing between start and completion.
    """

    def _record(self, index: int, doc_id: str) -> dict:
        return {
            "chunk_id": f"chunk-{index}",
            "document_id": doc_id,
            "text": f"content {index}",
            "source_system": "confluence",
            "source_type": "wiki_page",
            "title": "Test Page",
            "heading_path": ["Section"],
            "content_kind": "prose",
            "language": "en",
            "page_id": "12345",
            "space_key": "TEST",
        }

    async def test_packet_documents_are_persisted(self, mock_embedder, mock_storage_service):
        doc_id = "confluence:page:12345"
        documents = [{
            "document_id": doc_id,
            "title": "Golden Page",
            "url": "https://confluence.example.test/spaces/TEST/pages/12345",
            "page_id": "12345",
            "space_key": "TEST",
            "metadata": {"fixture": "yes"},
        }]

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        await use_case._execute_records_strict([self._record(1, doc_id)], documents)

        assert len(mock_storage_service.saved_documents) == 1
        saved = mock_storage_service.saved_documents[0]
        assert saved.title == "Golden Page"
        assert saved.url == "https://confluence.example.test/spaces/TEST/pages/12345"
        # Same source_id rule the chunks use, so both agree on what they belong to.
        assert saved.source_id == "12345"
        assert saved.source_type is SourceType.CONFLUENCE
        # Deterministic id => re-ingesting updates instead of duplicating.
        assert saved.id == uuid5(_DOCUMENT_ID_NAMESPACE, doc_id)
        assert saved.metadata["foundation_document_id"] == doc_id
        assert saved.metadata["space_key"] == "TEST"

    async def test_documents_without_a_usable_id_are_skipped(
        self, mock_embedder, mock_storage_service
    ):
        doc_id = "confluence:page:12345"
        documents = [
            {"document_id": doc_id, "title": "Kept"},
            {"title": "No id at all"},
        ]

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        await use_case._execute_records_strict([self._record(1, doc_id)], documents)

        assert [doc.title for doc in mock_storage_service.saved_documents] == ["Kept"]

    async def test_embedding_progress_is_reported_and_throttled(
        self, mock_embedder, mock_storage_service
    ):
        doc_id = "confluence:page:12345"
        records = [self._record(i, doc_id) for i in range(60)]
        documents = [{"document_id": doc_id, "title": "Test Page", "page_id": "12345"}]
        seen: list[tuple[int, int]] = []

        async def report(*, embedded_chunks: int, total_chunks: int) -> None:
            seen.append((embedded_chunks, total_chunks))

        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)
        await use_case._execute_records_strict(records, documents, report)

        # Every 25 chunks plus a final report, not once per chunk: a big packet
        # must not turn one job-status row into thousands of writes.
        assert seen == [(25, 60), (50, 60), (60, 60)]

    async def test_progress_is_optional(self, mock_embedder, mock_storage_service):
        doc_id = "confluence:page:12345"
        use_case = IngestChunkingPacket(mock_embedder, mock_storage_service)

        result = await use_case._execute_records_strict(
            [self._record(1, doc_id)], [{"document_id": doc_id, "title": "T"}]
        )

        assert result.chunks_ingested == 1
