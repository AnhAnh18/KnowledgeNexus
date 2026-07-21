from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from knowledgenexus.foundation.domain.models.tokenization import TokenizationResult


class TokenizerFailureCategory(StrEnum):
    ASSETS_MISSING = "tokenizer_assets_missing"
    ASSET_SIZE_MISMATCH = "tokenizer_asset_size_mismatch"
    ASSET_HASH_MISMATCH = "tokenizer_asset_hash_mismatch"
    IDENTITY_MISMATCH = "tokenizer_identity_mismatch"
    RUNTIME_VERSION_MISMATCH = "tokenizer_runtime_version_mismatch"
    CONFIGURATION_INVALID = "tokenizer_configuration_invalid"
    ASSET_DECODE_FAILED = "tokenizer_asset_decode_failed"
    LOAD_FAILED = "tokenizer_load_failed"
    OFFSET_INVALID = "token_offset_invalid"
    TOKENIZATION_FAILED = "tokenization_failed"


class TokenizerError(Exception):
    """Sanitized tokenizer failure carrying only a stable category."""

    def __init__(self, category: TokenizerFailureCategory) -> None:
        if not isinstance(category, TokenizerFailureCategory):
            raise TypeError("category expects TokenizerFailureCategory")
        self.category = category
        super().__init__(category.value)


class TokenizerPort(Protocol):
    def tokenize(self, *, text: str) -> TokenizationResult: ...
