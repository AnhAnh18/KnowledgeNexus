from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.symbol_index import SymbolParseResult


class SymbolParserPort(Protocol):
    def parse(self, *, path: str, language: str, source_text: str) -> SymbolParseResult: ...


__all__ = ["SymbolParserPort"]
