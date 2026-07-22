"""Tests for AgentBuilderAdapter — LLM provider implementation.

Covers: success path, HTTP errors, timeout, malformed response, empty text.
Uses unittest.mock to simulate Agent Builder API.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from knowledgenexus.chat.infrastructure.llm.agent_builder_adapter import (
    AgentBuilderAdapter,
    LLMProviderError,
)


def _make_api_response(text: str = "Hello from Agent Builder") -> dict:
    """Build a valid Agent Builder API response payload."""
    return {
        "outputs": [
            {
                "outputs": [
                    {
                        "results": {
                            "text": {"text": text},
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def adapter() -> AgentBuilderAdapter:
    return AgentBuilderAdapter(
        base_url="https://agent.example.com",
        api_key="test-key",
        agent_id="abc12345-6789-def0",
        timeout=5,
    )


def _make_response(status: int = 200, json_data: dict | None = None, text: str | None = None) -> httpx.Response:
    """Create an httpx.Response with a request attached (needed for raise_for_status)."""
    request = httpx.Request("POST", "https://agent.example.com/runner_api/v1/run/test")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=request)
    return httpx.Response(status, text=text or "", request=request)


def _make_mock_client(response: httpx.Response | None = None, exception: Exception | None = None):
    """Create a mock AsyncClient that returns the given response or raises exception."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    if exception:
        mock_client.post = AsyncMock(side_effect=exception)
    else:
        mock_client.post = AsyncMock(return_value=response)

    return mock_client


class TestAgentBuilderAdapterSuccess:
    """Verify happy path: API returns text → adapter returns (text, model)."""

    @pytest.mark.asyncio
    async def test_generate_success(self, adapter: AgentBuilderAdapter):
        resp = _make_response(200, json_data=_make_api_response("The SPen SDK is a development kit."))
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            text, model = await adapter.generate("What is SPen SDK?")

        assert text == "The SPen SDK is a development kit."
        assert "agent-builder" in model
        assert "abc12345" in model

    @pytest.mark.asyncio
    async def test_generate_sends_correct_payload(self, adapter: AgentBuilderAdapter):
        resp = _make_response(200, json_data=_make_api_response("answer"))
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            await adapter.generate("test prompt")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "runner_api/v1/run/abc12345-6789-def0" in str(url)
        assert "stream=false" in str(url)

        payload = call_args[1].get("json", {})
        assert payload["input_value"] == "test prompt"
        assert payload["input_type"] == "chat"
        assert payload["output_type"] == "chat"

        headers = call_args[1].get("headers", {})
        assert headers["x-api-key"] == "test-key"
        assert headers["Content-Type"] == "application/json"


class TestAgentBuilderAdapterErrors:
    """Verify error handling: HTTP errors, timeout, malformed response, empty text."""

    @pytest.mark.asyncio
    async def test_http_error_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        resp = _make_response(401, json_data={"detail": "Unauthorized"})
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="API error: 401"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_http_500_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        resp = _make_response(500, text="Internal Server Error")
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="API error: 500"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_request_timeout_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        mock_client = _make_mock_client(exception=httpx.ConnectTimeout("Connection timed out"))

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="request failed"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_connect_error_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        mock_client = _make_mock_client(exception=httpx.ConnectError("Connection refused"))

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="request failed"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_malformed_response_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        """Missing nested keys → KeyError → LLMProviderError."""
        resp = _make_response(200, json_data={"unexpected": "structure"})
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="Malformed"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_empty_outputs_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        """Empty outputs list → IndexError → LLMProviderError."""
        resp = _make_response(200, json_data={"outputs": []})
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="Malformed"):
                await adapter.generate("test")

    @pytest.mark.asyncio
    async def test_empty_text_raises_llm_provider_error(self, adapter: AgentBuilderAdapter):
        """Valid structure but empty text → LLMProviderError."""
        resp = _make_response(200, json_data=_make_api_response(""))
        mock_client = _make_mock_client(resp)

        with patch("knowledgenexus.chat.infrastructure.llm.agent_builder_adapter.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError, match="Empty response"):
                await adapter.generate("test")


class TestAgentBuilderAdapterConfig:
    """Verify adapter configuration."""

    def test_init_strips_trailing_slash(self):
        adapter = AgentBuilderAdapter(
            base_url="https://agent.example.com/",
            api_key="key",
            agent_id="abc12345",
        )
        assert adapter._base_url == "https://agent.example.com"

    def test_is_llm_port_subclass(self):
        from knowledgenexus.chat.ports.llm_port import LLMPort
        assert issubclass(AgentBuilderAdapter, LLMPort)
