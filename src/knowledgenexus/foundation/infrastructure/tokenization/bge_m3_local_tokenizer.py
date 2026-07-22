from __future__ import annotations

import hashlib
import hmac
import unicodedata
from importlib import metadata
from pathlib import Path
from typing import Protocol

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.tokenization import (
    CharacterSpan,
    TokenizationResult,
)
from knowledgenexus.foundation.ports.tokenizer_port import (
    TokenizerError,
    TokenizerFailureCategory,
)


_MODEL_NAME = "BAAI/bge-m3"
_TOKENIZER_FAMILY = "SentencePiece / XLM-R"
_TOKENIZER_REPOSITORY = "https://huggingface.co/BAAI/bge-m3"
_TOKENIZER_FILENAME = "tokenizer.json"


class _Encoding(Protocol):
    ids: list[int]
    offsets: list[tuple[int, int]]


class _RustTokenizer(Protocol):
    truncation: object | None
    padding: object | None

    def encode(self, sequence: str, add_special_tokens: bool = True) -> _Encoding: ...


def _raise(category: TokenizerFailureCategory) -> None:
    raise TokenizerError(category) from None


def _validate_profile_identity(profile: ChunkingProfile) -> None:
    if (
        profile.model_name != _MODEL_NAME
        or profile.tokenizer_name != _MODEL_NAME
        or profile.tokenizer_family != _TOKENIZER_FAMILY
        or profile.tokenizer_repository != _TOKENIZER_REPOSITORY
    ):
        _raise(TokenizerFailureCategory.IDENTITY_MISMATCH)


def _require_runtime_version(profile: ChunkingProfile) -> None:
    try:
        installed_version = metadata.version("tokenizers")
    except metadata.PackageNotFoundError:
        _raise(TokenizerFailureCategory.RUNTIME_VERSION_MISMATCH)
    if installed_version != profile.tokenizers_version:
        _raise(TokenizerFailureCategory.RUNTIME_VERSION_MISMATCH)


def _read_verified_assets(
    *, profile: ChunkingProfile, tokenizer_assets_dir: Path
) -> tuple[tuple[str, bytes], ...]:
    verified: list[tuple[str, bytes]] = []
    for asset in profile.tokenizer_assets:
        asset_path = tokenizer_assets_dir / asset.filename
        try:
            body = asset_path.read_bytes()
        except OSError:
            _raise(TokenizerFailureCategory.ASSETS_MISSING)
        if len(body) != asset.byte_size:
            _raise(TokenizerFailureCategory.ASSET_SIZE_MISMATCH)
        actual_hash = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual_hash, asset.sha256):
            _raise(TokenizerFailureCategory.ASSET_HASH_MISMATCH)
        verified.append((asset.filename, body))
    return tuple(verified)


def _tokenizer_from_str(serialized_tokenizer: str) -> _RustTokenizer:
    from tokenizers import Tokenizer

    return Tokenizer.from_str(serialized_tokenizer)


def _load_verified_tokenizer(
    *, profile: ChunkingProfile, tokenizer_assets_dir: Path
) -> _RustTokenizer:
    verified_assets = _read_verified_assets(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    tokenizer_bodies = [
        body for filename, body in verified_assets if filename == _TOKENIZER_FILENAME
    ]
    if len(tokenizer_bodies) != 1:
        _raise(TokenizerFailureCategory.IDENTITY_MISMATCH)
    try:
        serialized_tokenizer = tokenizer_bodies[0].decode("utf-8")
    except UnicodeDecodeError:
        _raise(TokenizerFailureCategory.ASSET_DECODE_FAILED)
    try:
        tokenizer = _tokenizer_from_str(serialized_tokenizer)
    except Exception:
        _raise(TokenizerFailureCategory.LOAD_FAILED)
    if tokenizer.truncation is not None or tokenizer.padding is not None:
        _raise(TokenizerFailureCategory.CONFIGURATION_INVALID)
    return tokenizer


class BgeM3LocalTokenizer:
    """Exact pinned BGE-M3 tokenizer loaded only from verified local bytes."""

    def __init__(
        self,
        *,
        profile: ChunkingProfile,
        tokenizer_assets_dir: Path,
    ) -> None:
        if not isinstance(profile, ChunkingProfile):
            raise TypeError("profile expects ChunkingProfile")
        if not isinstance(tokenizer_assets_dir, Path):
            raise TypeError("tokenizer_assets_dir expects pathlib.Path")
        _validate_profile_identity(profile)
        _require_runtime_version(profile)
        self._tokenizer = _load_verified_tokenizer(
            profile=profile,
            tokenizer_assets_dir=tokenizer_assets_dir,
        )

    def tokenize(self, *, text: str) -> TokenizationResult:
        if not isinstance(text, str):
            raise TypeError("text expects str")
        if not unicodedata.is_normalized("NFC", text):
            _raise(TokenizerFailureCategory.OFFSET_INVALID)
        if text == "":
            return TokenizationResult(spans=())

        try:
            encoding = self._tokenizer.encode(text, add_special_tokens=False)
            raw_offsets = tuple(encoding.offsets)
            token_id_count = len(encoding.ids)
        except Exception:
            _raise(TokenizerFailureCategory.TOKENIZATION_FAILED)

        if len(raw_offsets) != token_id_count:
            _raise(TokenizerFailureCategory.OFFSET_INVALID)

        spans: list[CharacterSpan] = []
        previous_start = -1
        previous_end = -1
        for raw_offset in raw_offsets:
            if (
                not isinstance(raw_offset, (tuple, list))
                or len(raw_offset) != 2
            ):
                _raise(TokenizerFailureCategory.OFFSET_INVALID)
            start, end = raw_offset
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or start < 0
                or start >= end
                or end > len(text)
                or start < previous_start
                or end < previous_end
            ):
                _raise(TokenizerFailureCategory.OFFSET_INVALID)
            spans.append(CharacterSpan(start=start, end=end))
            previous_start = start
            previous_end = end

        return TokenizationResult(spans=tuple(spans))
