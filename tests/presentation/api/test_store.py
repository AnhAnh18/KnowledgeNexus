from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.shared.di.container import AppContainer
from tests.conftest import VECTOR_SIZE, make_chunk


def _store_request_body(chunk):
    doc_id = str(chunk.document_id)
    return {
        "chunks": [
            {
                "chunk_id": chunk.id,
                "document_id": doc_id,
                "vector": chunk.vector,
                "core": {
                    "document_id": doc_id,
                    "source_type": chunk.payload.core.source_type.value,
                    "source_id": chunk.payload.core.source_id,
                    "title": chunk.payload.core.title,
                    "url": chunk.payload.core.url,
                    "chunk_index": chunk.payload.core.chunk_index,
                    "total_chunks": chunk.payload.core.total_chunks,
                    "indexed_at": chunk.payload.core.indexed_at.isoformat(),
                    "embedding_model": chunk.payload.core.embedding_model,
                },
                "content": chunk.payload.content,
                "extra": chunk.payload.extra,
            }
        ]
    }


@pytest.fixture
async def api_client(monkeypatch):
    chunk_storage = AsyncMock()
    chunk_storage.get_stats.return_value = {
        "qdrant": {"collection": "test", "points_count": 2, "vector_size": VECTOR_SIZE},
        "sqlite": {"chunks": 2, "documents": 1},
    }
    document_repo = AsyncMock()
    engine = AsyncMock()
    engine.connect.return_value.__aenter__.return_value.exec_driver_sql = AsyncMock()

    container = AppContainer(
        settings=MagicMock(storage_mode=MagicMock(value="hybrid")),
        engine=engine,
        session_factory=MagicMock(),
        chunk_repo=MagicMock(),
        document_repo=document_repo,
        ingest_job_repo=MagicMock(),
        vector_store=MagicMock(),
        chunk_storage=chunk_storage,
    )


    async def fake_init_container(settings):
        return container

    async def fake_shutdown_container():
        return None

    import importlib
    import knowledgenexus.shared.di.container as container_module

    # init_container/shutdown_container are imported locally inside lifespan(),
    # so patch them at source — the runtime import will pick up the patched versions.
    monkeypatch.setattr(container_module, "init_container", fake_init_container)
    monkeypatch.setattr(container_module, "shutdown_container", fake_shutdown_container)

    # get_container is imported at module level in store.py, so patch it there.
    store_module = importlib.import_module("knowledgenexus.presentation.api.v1.store")
    monkeypatch.setattr(store_module, "get_container", lambda: container)

    app_module = importlib.import_module("knowledgenexus.presentation.api.app")
    app = app_module.app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, chunk_storage, document_repo


@pytest.mark.asyncio
async def test_store_chunks_success(api_client):
    client, chunk_storage, _ = api_client
    chunk = make_chunk()

    response = await client.post("/api/v1/store/chunks", json=_store_request_body(chunk))

    assert response.status_code == 200
    assert response.json() == {"chunks_stored": 1}
    chunk_storage.save.assert_awaited_once()
    saved_chunks = chunk_storage.save.await_args.args[0]
    assert len(saved_chunks) == 1
    assert saved_chunks[0].id == chunk.id
    assert saved_chunks[0].content == chunk.content


@pytest.mark.asyncio
async def test_store_chunks_empty_returns_400(api_client):
    client, chunk_storage, _ = api_client

    response = await client.post("/api/v1/store/chunks", json={"chunks": []})

    assert response.status_code == 400
    assert response.json()["detail"] == "No chunks provided"
    chunk_storage.save.assert_not_called()


@pytest.mark.asyncio
async def test_store_chunks_document_id_mismatch_returns_400(api_client):
    client, chunk_storage, _ = api_client
    chunk = make_chunk()
    body = _store_request_body(chunk)
    body["chunks"][0]["document_id"] = str(uuid4())

    response = await client.post("/api/v1/store/chunks", json=body)

    assert response.status_code == 400
    assert "document_id must match" in response.json()["detail"]
    chunk_storage.save.assert_not_called()


@pytest.mark.asyncio
async def test_get_store_stats(api_client):
    client, chunk_storage, _ = api_client

    response = await client.get("/api/v1/store/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["qdrant"]["points_count"] == 2
    assert payload["sqlite"]["chunks"] == 2
    chunk_storage.get_stats.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_document_returns_204(api_client):
    client, chunk_storage, document_repo = api_client
    doc_id = str(uuid4())

    response = await client.delete(f"/api/v1/store/documents/{doc_id}")

    assert response.status_code == 204
    chunk_storage.delete_by_document_id.assert_awaited_once_with(doc_id)
    document_repo.delete.assert_awaited_once_with(doc_id)
