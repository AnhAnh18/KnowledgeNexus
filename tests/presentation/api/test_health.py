from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from knowledgenexus.shared.di.container import AppContainer


@pytest.fixture
async def api_client(monkeypatch):
    engine = MagicMock()
    conn = AsyncMock()
    conn.exec_driver_sql = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn
    engine.connect.return_value.__aexit__.return_value = None

    vector_store = AsyncMock()
    vector_store.health_check.return_value = True

    settings = MagicMock(
        storage_mode=MagicMock(value="hybrid"),
        qdrant_url="http://localhost:6333",
    )

    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=MagicMock(),
        chunk_repo=MagicMock(),
        document_repo=MagicMock(),
        vector_store=vector_store,
        chunk_storage=MagicMock(),
    )

    async def fake_init_container(settings):
        return container

    async def fake_shutdown_container():
        return None

    import importlib
    import knowledgenexus.shared.di.container as container_module

    monkeypatch.setattr(container_module, "init_container", fake_init_container)
    monkeypatch.setattr(container_module, "shutdown_container", fake_shutdown_container)

    health_module = importlib.import_module("knowledgenexus.presentation.api.v1.health")
    monkeypatch.setattr(health_module, "get_container", lambda: container)
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)

    app_module = importlib.import_module("knowledgenexus.presentation.api.app")
    app = app_module.app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, engine, vector_store, settings


@pytest.mark.asyncio
async def test_health_all_ok(api_client):
    client, engine, vector_store, _ = api_client

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["storage_mode"] == "hybrid"
    assert payload["sqlite"] == "ok"
    assert payload["qdrant"] == "ok"
    assert payload["qdrant_url"] == "http://localhost:6333"
    engine.connect.return_value.__aenter__.return_value.exec_driver_sql.assert_awaited_once_with("SELECT 1")
    vector_store.health_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_sqlite_error(api_client):
    client, engine, vector_store, _ = api_client
    engine.connect.side_effect = RuntimeError("db down")

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["sqlite"] == "error"
    assert payload["qdrant"] == "ok"


@pytest.mark.asyncio
async def test_health_qdrant_error(api_client):
    client, engine, vector_store, _ = api_client
    vector_store.health_check.side_effect = RuntimeError("qdrant down")

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["sqlite"] == "ok"
    assert payload["qdrant"] == "error"


@pytest.mark.asyncio
async def test_health_qdrant_returns_false(api_client):
    client, engine, vector_store, _ = api_client
    vector_store.health_check.return_value = False

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["qdrant"] == "error"


@pytest.mark.asyncio
async def test_health_all_degraded(api_client):
    client, engine, vector_store, _ = api_client
    engine.connect.side_effect = RuntimeError("db down")
    vector_store.health_check.side_effect = RuntimeError("qdrant down")

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["sqlite"] == "error"
    assert payload["qdrant"] == "error"
