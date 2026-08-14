"""Ingest chunks từ resource/chunks.json (JSONL format) vào Qdrant.
Chạy:
    python scripts/ingest_chunks_from_json.py
Yêu cầu:
    - Qdrant server chạy tại http://localhost:6333
      (chạy: docker run -p 6333:6333 qdrant/qdrant)
    - pip install qdrant-client pyyaml FlagEmbedding
    - Model BGE-M3 tại: D:\\Tools\\BAAI_bge-m3
Script này:
1. Đọc chunks từ resource/chunks.json (JSONL: mỗi dòng = 1 chunk)
2. Embed từng chunk bằng BGE-M3
3. Upsert vào Qdrant collection
4. Báo cáo số chunks đã ingest
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Đảm bảo stdout dùng UTF-8 (tránh lỗi tiếng Việt trên Windows console)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# Add src to path for standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import (
    Chunk,
    ChunkPayload,
    CoreChunkMetadata,
)
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.infrastructure.embedding.bge_m3_embedder import BgeM3Embedder
from knowledgenexus.indexing.infrastructure.vector_store.qdrant_store import (
    QdrantVectorStore,
)
from knowledgenexus.shared.config.settings import Settings
from knowledgenexus.shared.di.container import init_container

# --- Cấu hình ---
QDRANT_URL = "http://localhost:6333"
CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "config" / "qdrant.collection.hybrid.yaml")
COLLECTION_NAME = "Confluence"

# Đường dẫn model BGE-M3 offline
MODEL_PATH = r"D:\Tools\BAAI_bge-m3"

# Đường dẫn chunks.json
CHUNKS_JSON_PATH = str(Path(__file__).resolve().parents[1] / "resource" / "chunks.json")


def _map_source_type(source_type_str: str) -> SourceType:
    """Map source_type từ chunks.json sang SourceType enum."""
    mapping = {
        "wiki_page": SourceType.CONFLUENCE,
        "jira_issue": SourceType.CONFLUENCE,  # Map JIRA to CONFLUENCE (no JIRA type in enum)
        "document": SourceType.FILE,
    }
    return mapping.get(source_type_str, SourceType.CONFLUENCE)


async def _create_chunk_from_json(
    embedder: BgeM3Embedder,
    *,
    doc_id: str,
    chunk_data: dict,
) -> Chunk:
    """Tạo Chunk từ dữ liệu chunks.json với vector thật từ BGE-M3, dùng document_id có sẵn."""
    source_type = _map_source_type(chunk_data.get("source_type", "wiki_page"))

    core = CoreChunkMetadata(
        document_id=doc_id,
        source_type=source_type,
        source_id=chunk_data.get("chunk_id", str(uuid4())),  # Original chunk_id từ JSON (không phải UUID)
        title=chunk_data.get("title", ""),
        url=None,
        chunk_index=0,
        total_chunks=1,
        indexed_at=datetime.now(UTC),
        embedding_model=embedder.model_name,
    )

    # Embed content thật bằng BGE-M3
    content = chunk_data.get("text", "")
    embeddings = await embedder.embed([content])
    embedding = embeddings[0]
    vector = embedding.values
    sparse = embedding.sparse

    # Tạo extra metadata từ dữ liệu chunks.json
    extra = {
        k: v for k, v in chunk_data.items()
        if k not in ["text", "title", "document_id", "chunk_id", "source_type"]
    }

    # Sanitize heading_path: convert list to string (take first element or join)
    if "heading_path" in extra and isinstance(extra["heading_path"], list):
        heading_list = extra["heading_path"]
        extra["heading_path"] = heading_list[0] if heading_list else None

    # Return Chunk with both dense and sparse vectors (if available)
    return Chunk(
        id=str(uuid4()),  # Qdrant yêu cầu UUID format cho point.id
        payload=ChunkPayload(core=core, content=content, extra=extra),
        dense_vector=vector,
        sparse_vector=sparse,
    )


async def main() -> None:
    print("=" * 70)
    print("Ingest chunks từ resource/chunks.json vào Qdrant")
    print("=" * 70)

    # ---------------------------------------------------------------
    # 1. Khởi tạo BGE-M3 embedder + QdrantVectorStore
    # ---------------------------------------------------------------
    print("\n[1/5] Khởi tạo BGE-M3 embedder...")
    print(f"      Model: {MODEL_PATH}")
    print("[Loading] Model is loading...")
    embedder = BgeM3Embedder(model_name=MODEL_PATH, device="cpu", return_sparse=True)
    print(f"[OK] Model loaded: {embedder.model_name}")
    print(f"     Dimension: {embedder.dimension}")

    print("\n[2/5] Khởi tạo QdrantVectorStore...")
    print(f"      URL: {QDRANT_URL}")
    print(f"      Collection: {COLLECTION_NAME}")
    print(f"      Config: {CONFIG_PATH}")

    store = await QdrantVectorStore.create(
        url=QDRANT_URL,
        config_path=CONFIG_PATH,
        collection_name_override=COLLECTION_NAME,
    )
    print("[OK] Store đã khởi tạo, collection đã được tạo (nếu chưa có).")

    # Health check
    healthy = await store.health_check()
    print(f"[Health] Qdrant reachable: {healthy}")

    # ---------------------------------------------------------------
    # 2. Đọc chunks từ JSONL + tạo documents
    # ---------------------------------------------------------------
    print(f"\n[3/5] Đọc chunks từ {CHUNKS_JSON_PATH}...")
    chunks_data = []
    try:
        with open(CHUNKS_JSON_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunks_data.append(json.loads(line))
    except Exception as e:
        print(f"[ERROR] Không thể đọc chunks.json: {e}")
        embedder.close()
        await store.close()
        return

    print(f"[OK] Đã đọc {len(chunks_data)} chunks từ JSONL")

    # Khởi tạo container để access document_repo
    print("\n[Creating documents...]")
    settings = Settings()
    container = await init_container(settings)

    # Tạo documents từ chunks_data (dedup bằng document_id)
    doc_map: dict[str, Document] = {}  # document_id -> Document
    for chunk_data in chunks_data:
        doc_id = chunk_data.get("document_id", str(uuid4()))
        if doc_id not in doc_map:
            source_type = _map_source_type(chunk_data.get("source_type", "wiki_page"))
            doc = Document(
                id=uuid4() if not doc_id.startswith("00000000") else doc_id,  # Use existing ID if valid UUID
                title=chunk_data.get("title", "Unknown")[:512],
                content=chunk_data.get("text", ""),
                source_type=source_type,
                source_id=chunk_data.get("chunk_id", str(uuid4())),
            )
            doc_map[str(doc.id)] = doc
            await container.document_repo.save(doc)

    print(f"[OK] Saved {len(doc_map)} documents")

    # ---------------------------------------------------------------
    # 3. Embed + tạo Chunk objects
    # ---------------------------------------------------------------
    print("\n[4/5] Embed chunks bằng BGE-M3...")
    chunks: list[Chunk] = []
    skipped = 0

    for i, chunk_data in enumerate(chunks_data, 1):
        try:
            content = chunk_data.get("text", "")
            title = chunk_data.get("title", "")[:50]  # Cắt để hiển thị

            # Lấy document_id từ chunk_data, sử dụng doc_map để get đúng document
            chunk_doc_id = chunk_data.get("document_id", str(uuid4()))
            doc = next((d for d in doc_map.values() if d.source_id == chunk_data.get("chunk_id")), None)
            actual_doc_id = str(doc.id) if doc else chunk_doc_id

            print(f"      [{i}/{len(chunks_data)}] Embedding: \"{title}...\"", end="")
            chunk = await _create_chunk_from_json(embedder, doc_id=actual_doc_id, chunk_data=chunk_data)
            chunks.append(chunk)
            print(f" [OK] dim={len(chunk.dense_vector)}")
        except Exception as e:
            print(f" [SKIP] {type(e).__name__}: {e}")
            skipped += 1

    if skipped > 0:
        print(f"\n[WARNING] {skipped} chunks bị skip do lỗi")

    # ---------------------------------------------------------------
    # 4. Upsert vào Qdrant + SQLite
    # ---------------------------------------------------------------
    print(f"\n[5/5] Upsert {len(chunks)} chunks vào Qdrant...")
    if chunks:
        await store.upsert_slim(chunks)
        # Save metadata to SQLite
        await container.chunk_repo.save_batch(chunks)
        print(f"[OK] Đã upsert {len(chunks)} points.")

        # Stats
        stats = await store.get_stats()
        print(f"[Stats] {stats}")
    else:
        print("[WARNING] Không có chunks để upsert")

    # ---------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("[Done] Ingest hoàn tất. Đang đóng connection...")
    embedder.close()
    await store.close()
    print(f"Collection '{COLLECTION_NAME}' đã được cập nhật trong Qdrant.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())