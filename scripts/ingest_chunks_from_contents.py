"""Demo: Khởi tạo Qdrant, tạo collection, thêm points và search (chạy thật).
Chạy:
    python scripts/ingest_chunks_from_contents.py
Yêu cầu:
    - Qdrant server chạy tại http://localhost:6333
      (chạy: docker run -p 6333:6333 qdrant/qdrant)
    - pip install qdrant-client pyyaml FlagEmbedding
    - Model BGE-M3 tại: D:\\Tools\\BAAI_bge-m3
Script này dùng trực tiếp QdrantVectorStore + BgeM3Embedder của project
KnowledgeNexus để đảm bảo tương thích với schema config
(config/qdrant.collection.yaml) và vector thật 1024-dim.
"""

from __future__ import annotations

import asyncio
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
COLLECTION_NAME = "Confluence"  # using the current Confluence collection

# Đường dẫn model BGE-M3 offline
MODEL_PATH = r"D:\Tools\BAAI_bge-m3"


async def _make_chunk(
    embedder: BgeM3Embedder,
    *,
    doc_id: str,
    content: str,
    source_id: str,
    source_type: SourceType = SourceType.CONFLUENCE,
) -> Chunk:
    """Tạo 1 Chunk với vector thật từ BGE-M3 embedder, dùng document_id có sẵn."""
    core = CoreChunkMetadata(
        document_id=doc_id,
        source_type=source_type,
        source_id=source_id,
        title="Demo Document",
        url=None,
        chunk_index=0,
        total_chunks=1,
        indexed_at=datetime.now(UTC),
        embedding_model=embedder.model_name,
    )
    # Embed content thật bằng BGE-M3 và lấy sparse nếu có
    embedding = (await embedder.embed([content]))[0]
    vector = embedding.values
    sparse = embedding.sparse
    return Chunk(
        id=str(uuid4()),
        payload=ChunkPayload(core=core, content=content, extra={}),
        dense_vector=vector,
        sparse_vector=sparse,
    )


async def main() -> None:
    print("=" * 70)
    print("Demo: Qdrant end-to-end (init -> create collection -> upsert -> search)")
    print("      Sử dụng vector THẬT từ BGE-M3 embedder")
    print("=" * 70)

    # ---------------------------------------------------------------
    # 1. Khởi tạo BGE-M3 embedder + QdrantVectorStore
    # ---------------------------------------------------------------
    print("\n[1/6] Khởi tạo BGE-M3 embedder...")
    print(f"      Model: {MODEL_PATH}")
    print("[Loading] Model is loading...")
    embedder = BgeM3Embedder(model_name=MODEL_PATH, device="cpu", return_sparse=True)
    print(f"[OK] Model loaded: {embedder.model_name}")
    print(f"     Dimension: {embedder.dimension}")

    print("\n[2/6] Khởi tạo QdrantVectorStore...")
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
    # 2. Tạo dữ liệu demo (documents + chunks) + embed thật
    # ---------------------------------------------------------------
    print("\n[3/6] Tạo dữ liệu demo (5 documents + chunks) + embed bằng BGE-M3...")
    contents = [
        "Qdrant is an open-source vector search engine for high-dimensional vectors.",
        "BGE-M3 is a multilingual embedding model supporting 100+ languages.",
        "KnowledgeNexus is a RAG platform combining Qdrant and BGE-M3.",
        "KnowledgeNexus has made by 3 members in SpenSDK",
        "3 members are Ryan, Tez, Bin",
    ]
    source_ids = [
        "page-qdrant-intro",
        "page-bge-m3",
        "page-knowledgenexus",
        "page-vector-db",
        "page-rag",
    ]

    # Tạo documents trước
    print("      [Creating documents...]")
    settings = Settings()
    container = await init_container(settings)

    documents: list[Document] = []
    for content, sid in zip(contents, source_ids, strict=True):
        doc = Document(
            title=f"Demo: {sid}",
            content=content,
            source_type=SourceType.CONFLUENCE,
            source_id=sid,
        )
        documents.append(doc)
        await container.document_repo.save(doc)
    print(f"      [OK] Saved {len(documents)} documents")

    # Tạo chunks với document_id từ documents
    chunks: list[Chunk] = []
    content_map: dict[str, str] = {}  # chunk_id -> full content (để in kết quả search)
    for i, (doc, content) in enumerate(zip(documents, contents, strict=True), 1):
        print(f"      [{i}/5] Embedding: \"{content[:50]}...\"")
        chunk = await _make_chunk(embedder, doc_id=str(doc.id), content=content, source_id=doc.source_id)
        chunks.append(chunk)
        content_map[chunk.id] = content
        print(f"{chunk.id[:8]}... dim={len(chunk.dense_vector)}")


    # ---------------------------------------------------------------
    # 3. Upsert (thêm points vào Qdrant)
    # ---------------------------------------------------------------
    print("\n[4/6] Upsert 5 chunks vào Qdrant...")
    await store.upsert_slim(chunks)
    # Save metadata to SQLite
    await container.chunk_repo.save_batch(chunks)
    print("[OK] Đã upsert 5 points.")

    # Stats
    stats = await store.get_stats()
    print(f"[Stats] {stats}")

    # ---------------------------------------------------------------
    # 4. Search (tìm kiếm tương tự) - query thật
    # ---------------------------------------------------------------
    print("\n[5/6] Search (top 3)...")
    query_text = "What is Qdrant vector database?"
    print(f'      Query: "{query_text}"')
    print("      [Embedding query with BGE-M3...]")
    query_vector = (await embedder.embed_query(query_text)).values
    print(f"      Query vector dim: {len(query_vector)}")

    results = await store.search(dense_vector=query_vector, top_k=3)

    print(f"\n      Kết quả ({len(results)} hits):")
    for rank, hit in enumerate(results, 1):
        full_content = content_map.get(hit.chunk.id, "(content not available)")
        print(
            f"      #{rank}  score={hit.score:.4f}  "
            f"chunk_id={hit.chunk.id[:8]}...  "
            f"source_id={hit.chunk.payload.core.source_id}"
        )
        print(f"           content: \"{full_content}\"")


    # ---------------------------------------------------------------
    # 5. Search với filter (theo source_type)
    # ---------------------------------------------------------------
    print("\n[6/6] Search có filter (source_type=CONFLUENCE, top 2)...")
    filtered_results = await store.search(
        dense_vector=query_vector,
        top_k=2,
        filters={"source_type": str(SourceType.CONFLUENCE)},
    )
    print(f"\n      Kết quả filter ({len(filtered_results)} hits):")
    for rank, hit in enumerate(filtered_results, 1):
        full_content = content_map.get(hit.chunk.id, "(content not available)")
        print(
            f"      #{rank}  score={hit.score:.4f}  "
            f"source_id={hit.chunk.payload.core.source_id}"
        )
        print(f"           content: \"{full_content}\"")


    # ---------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("[Done] Demo hoàn tất. Đang đóng connection...")
    embedder.close()
    await store.close()
    print(f"Collection '{COLLECTION_NAME}' vẫn còn trong Qdrant.")
    print(f"  -> Xoá bằng: curl -X DELETE {QDRANT_URL}/collections/{COLLECTION_NAME}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())