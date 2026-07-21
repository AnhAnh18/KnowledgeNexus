from __future__ import annotations

from abc import ABC, abstractmethod


class LLMPort(ABC):
    """Abstract LLM port — swap providers (Agent Builder, Gauss, Gemini, etc.)."""

    @abstractmethod
    async def generate(self, prompt: str) -> tuple[str, str]:
        """Generate text from prompt. Returns (text, model_name)."""
        ...
