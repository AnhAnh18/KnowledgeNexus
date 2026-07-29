"""Ingest data/eval/corpus into SQLite + Qdrant with deterministic document IDs.

Usage (API not required — writes via DI container):

    uv run python scripts/ingest_eval_corpus.py

Then baseline dense (API must be running for kn-eval HTTP):

    uv run knowledgenexus
    uv run kn-eval --layer 1 --label dense-baseline
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.value_objects.embedding_vector import SparseVector
from knowledgenexus.shared.config.settings import get_settings
from knowledgenexus.shared.di.container import get_container, init_container, shutdown_container

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150
EMBEDDING_BATCH_SIZE = 16
EVAL_NAMESPACE = "knowledgenexus-eval"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def corpus_dir() -> Path:
    return repo_root() / "data" / "eval" / "corpus"


def deterministic_document_id(source_id: str) -> UUID:
    digest = hashlib.md5(f"{EVAL_NAMESPACE}:{source_id}".encode()).digest()
    return UUID(bytes=digest)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text or not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        if end >= text_len:
            chunks.append(text[start:].strip())
            break
        newline_pos = text.rfind("\n", start, end)
        if newline_pos > start + chunk_size // 2:
            end = newline_pos + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end - overlap
    return chunks


def generate_chunk_id(document_id: str, chunk_index: int) -> str:
    raw = f"{document_id}:{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


async def ingest_file(path: Path, root: Path, container) -> int:
    content = path.read_text(encoding="utf-8")
    rel = path.relative_to(root)
    source_id = str(rel).replace("\\", "/").removesuffix(".md")
    doc_id = deterministic_document_id(source_id)
    title = path.stem.replace("-", " ").replace("_", " ").title()

    document = Document(
        title=title,
        content=content,
        source_type=SourceType.FILE,
        source_id=source_id,
        id=doc_id,
        url=None,
    )
    parts = chunk_text(content)
    if not parts:
        print(f"  skip empty: {source_id}")
        return 0

    embedder = container.get_embedder()
    vectors: list[list[float]] = []
    sparse_vectors: list[SparseVector | None] = []
    for i in range(0, len(parts), EMBEDDING_BATCH_SIZE):
        batch = parts[i : i + EMBEDDING_BATCH_SIZE]
        embeddings = await embedder.embed(batch)
        vectors.extend([e.values for e in embeddings])
        for e in embeddings:
            if e.sparse is not None:
                sparse_vectors.append(e.sparse)
            else:
                sparse_vectors.append(None)

    now = datetime.now()
    chunks: list[Chunk] = []
    for idx, (text, vector) in enumerate(zip(parts, vectors, strict=True)):
        sv = sparse_vectors[idx] if idx < len(sparse_vectors) else None
        chunks.append(
            Chunk(
                id=generate_chunk_id(str(doc_id), idx),
                payload=ChunkPayload(
                    core=CoreChunkMetadata(
                        document_id=doc_id,
                        source_type=SourceType.FILE,
                        source_id=source_id,
                        title=title,
                        url=None,
                        chunk_index=idx,
                        total_chunks=len(parts),
                        indexed_at=now,
                        embedding_model=embedder.model_name,
                    ),
                    content=text,
                    extra={"file_path": str(rel).replace("\\", "/")},
                ),
                dense_vector=vector,
                sparse_vector=sv,
            )
        )

    # Replace any previous vectors/docs for this source
    await container.chunk_storage.delete_by_source_id(SourceType.FILE, source_id)
    await container.chunk_storage.save_document_and_chunks(document, chunks)
    print(f"  ok {source_id} -> {len(chunks)} chunks (doc_id={doc_id})")
    return len(chunks)


async def main() -> int:
    root = corpus_dir()
    if not root.is_dir():
        print(f"Corpus missing: {root}")
        return 1
    files = sorted(root.glob("*.md"))
    if not files:
        print(f"No markdown in {root}")
        return 1

    print(f"Ingesting {len(files)} eval docs from {root}")
    settings = get_settings()
    print(f"  collection: {settings.qdrant_collection}")
    print(f"  retrieval_mode: {settings.retrieval_mode}")
    await init_container(settings)
    try:
        container = get_container()
        total = 0
        for path in files:
            total += await ingest_file(path, root, container)
        print(f"Done. chunks={total}")
    finally:
        await shutdown_container()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
