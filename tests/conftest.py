from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk, ChunkPayload, CoreChunkMetadata

VECTOR_SIZE = 1024


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tokenizer-assets-dir",
        action="store",
        default=None,
        help="Explicit external BGE-M3 tokenizer asset directory",
    )


@pytest.fixture
def tokenizer_assets_dir(request: pytest.FixtureRequest) -> Path:
    raw_path = request.config.getoption("--tokenizer-assets-dir")
    if raw_path is None:
        pytest.fail(
            "asset-backed tokenizer tests require --tokenizer-assets-dir; "
            "they must not skip or use an implicit cache"
        )
    path = Path(raw_path)
    if not path.is_dir():
        pytest.fail("--tokenizer-assets-dir must identify an existing directory")
    return path


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).resolve().parents[1]

def qdrant_available() -> bool:
    try:
        import httpx

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        resp = httpx.get(f"{url}/collections", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False

def make_chunk(
    *,
    document_id: UUID | None = None,
    chunk_id: str | None = None,
    source_id: str = "test-source-1",
    content: str = "sample chunk content",
    vector_size: int = VECTOR_SIZE,
    vector_value: float = 0.01,
    extra: dict | None = None,
) -> Chunk:
    doc_id = document_id or uuid4()
    core = CoreChunkMetadata(
        document_id=doc_id,
        source_type=SourceType.CONFLUENCE,
        source_id=source_id,
        title="Test document",
        url="https://example.com/page",
        chunk_index=0,
        total_chunks=1,
        indexed_at=datetime.now(UTC),
        embedding_model="BAAI/bge-m3",
    )
    return Chunk(
        id=chunk_id or str(uuid4()),
        payload=ChunkPayload(core=core, content=content, extra=extra or {}),
        vector=[vector_value] * vector_size,
    )
