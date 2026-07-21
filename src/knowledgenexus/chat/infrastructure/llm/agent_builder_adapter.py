from __future__ import annotations

import httpx

from knowledgenexus.chat.ports.llm_port import LLMPort


class LLMProviderError(RuntimeError):
    """Raised when LLM provider fails."""


class AgentBuilderAdapter(LLMPort):

    def __init__(self, base_url: str, api_key: str, agent_id: str, timeout: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._agent_id = agent_id
        self._timeout = timeout

    async def generate(self, prompt: str) -> tuple[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }
        payload = {
            "input_value": prompt,
            "input_type": "chat",
            "output_type": "chat",
        }
        url = f"{self._base_url}/runner_api/v1/run/{self._agent_id}?stream=false"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            raise LLMProviderError(
                f"Agent Builder API error: {e.response.status_code} {e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise LLMProviderError(f"Agent Builder request failed: {e}") from e

        try:
            text = data["outputs"][0]["outputs"][0]["results"]["text"]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMProviderError(
                f"Malformed Agent Builder response: {e}"
            ) from e

        if not text:
            raise LLMProviderError("Empty response from Agent Builder")

        model = f"agent-builder:{self._agent_id[:8]}"
        return text, model
