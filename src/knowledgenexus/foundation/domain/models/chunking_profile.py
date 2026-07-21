from __future__ import annotations

import re
from dataclasses import dataclass


_EXPECTED_CHUNKER_VERSION = "1.2.0"
_EXPECTED_MODEL_NAME = "BAAI/bge-m3"
_EXPECTED_TOKENIZER_FAMILY = "SentencePiece / XLM-R"
_EXPECTED_PROFILE_STATUS = "provisional_until_benchmark"
_EXPECTED_ACTIVE_PROFILE = "medium"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def _require_positive_integer(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} expects an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _require_exact_identity(field_name: str, value: object, expected: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} expects str")
    if value != expected:
        raise ValueError(f"{field_name} does not match the active contract")


def _require_version(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} expects str")
    if _VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a pinned semantic version")


@dataclass(frozen=True, order=True)
class TokenizerAsset:
    """One immutable file required by the external tokenizer bundle."""

    filename: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str):
            raise TypeError("TokenizerAsset.filename expects str")
        if (
            not self.filename
            or self.filename in {".", ".."}
            or "/" in self.filename
            or "\\" in self.filename
        ):
            raise ValueError("TokenizerAsset.filename must be a plain file name")
        _require_positive_integer("TokenizerAsset.byte_size", self.byte_size)
        if not isinstance(self.sha256, str):
            raise TypeError("TokenizerAsset.sha256 expects str")
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("TokenizerAsset.sha256 must be lowercase SHA-256")


@dataclass(frozen=True)
class ChunkingProfile:
    """Validated active chunking and tokenizer contract, with no filesystem state."""

    chunker_version: str
    profile_status: str
    active_profile: str
    model_name: str
    tokenizer_name: str
    tokenizer_family: str
    vector_dimension: int
    maximum_model_tokens: int
    target_tokens: int
    minimum_tokens: int
    hard_maximum_tokens: int
    overlap_tokens: int
    code_window_target_tokens: int
    code_window_max_lines: int
    code_window_overlap_lines: int
    tokenizer_repository: str
    tokenizer_revision: str
    observed_license: str
    provenance_url: str
    tokenizer_assets: tuple[TokenizerAsset, ...]
    transformers_version: str
    tokenizers_version: str
    sentencepiece_version: str

    def __post_init__(self) -> None:
        _require_exact_identity(
            "ChunkingProfile.chunker_version",
            self.chunker_version,
            _EXPECTED_CHUNKER_VERSION,
        )
        _require_exact_identity(
            "ChunkingProfile.profile_status",
            self.profile_status,
            _EXPECTED_PROFILE_STATUS,
        )
        _require_exact_identity(
            "ChunkingProfile.active_profile",
            self.active_profile,
            _EXPECTED_ACTIVE_PROFILE,
        )
        _require_exact_identity(
            "ChunkingProfile.model_name", self.model_name, _EXPECTED_MODEL_NAME
        )
        _require_exact_identity(
            "ChunkingProfile.tokenizer_name",
            self.tokenizer_name,
            _EXPECTED_MODEL_NAME,
        )
        _require_exact_identity(
            "ChunkingProfile.tokenizer_family",
            self.tokenizer_family,
            _EXPECTED_TOKENIZER_FAMILY,
        )

        integer_fields = (
            ("vector_dimension", self.vector_dimension),
            ("maximum_model_tokens", self.maximum_model_tokens),
            ("target_tokens", self.target_tokens),
            ("minimum_tokens", self.minimum_tokens),
            ("hard_maximum_tokens", self.hard_maximum_tokens),
            ("overlap_tokens", self.overlap_tokens),
            ("code_window_target_tokens", self.code_window_target_tokens),
            ("code_window_max_lines", self.code_window_max_lines),
            ("code_window_overlap_lines", self.code_window_overlap_lines),
        )
        for field_name, value in integer_fields:
            _require_positive_integer(f"ChunkingProfile.{field_name}", value)

        if not (
            self.minimum_tokens
            <= self.target_tokens
            <= self.hard_maximum_tokens
            < self.maximum_model_tokens
        ):
            raise ValueError(
                "ChunkingProfile token limits must satisfy minimum <= target <= "
                "hard maximum < model maximum"
            )
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("ChunkingProfile.overlap_tokens must be below target_tokens")
        if self.code_window_target_tokens > self.hard_maximum_tokens:
            raise ValueError(
                "ChunkingProfile.code_window_target_tokens must not exceed the hard maximum"
            )
        if self.code_window_overlap_lines >= self.code_window_max_lines:
            raise ValueError(
                "ChunkingProfile.code_window_overlap_lines must be below the line limit"
            )

        if not isinstance(self.tokenizer_repository, str):
            raise TypeError("ChunkingProfile.tokenizer_repository expects str")
        if self.tokenizer_repository != "https://huggingface.co/BAAI/bge-m3":
            raise ValueError(
                "ChunkingProfile.tokenizer_repository does not match the active contract"
            )
        if not isinstance(self.tokenizer_revision, str):
            raise TypeError("ChunkingProfile.tokenizer_revision expects str")
        if _REVISION_PATTERN.fullmatch(self.tokenizer_revision) is None:
            raise ValueError(
                "ChunkingProfile.tokenizer_revision must be a full lowercase commit SHA"
            )
        if not isinstance(self.observed_license, str):
            raise TypeError("ChunkingProfile.observed_license expects str")
        if self.observed_license != "MIT":
            raise ValueError(
                "ChunkingProfile.observed_license does not match the recorded provenance"
            )
        if not isinstance(self.provenance_url, str):
            raise TypeError("ChunkingProfile.provenance_url expects str")
        if self.provenance_url != (
            f"{self.tokenizer_repository}/tree/{self.tokenizer_revision}"
        ):
            raise ValueError(
                "ChunkingProfile.provenance_url must identify the pinned tokenizer revision"
            )

        if isinstance(self.tokenizer_assets, (str, bytes)):
            raise TypeError("ChunkingProfile.tokenizer_assets expects a collection")
        assets = tuple(self.tokenizer_assets)
        if not assets:
            raise ValueError("ChunkingProfile.tokenizer_assets must not be empty")
        if not all(isinstance(asset, TokenizerAsset) for asset in assets):
            raise TypeError(
                "ChunkingProfile.tokenizer_assets expects TokenizerAsset entries"
            )
        filenames = [asset.filename for asset in assets]
        if len(filenames) != len(set(filenames)):
            raise ValueError("ChunkingProfile tokenizer asset names must be unique")
        if filenames != sorted(filenames):
            raise ValueError("ChunkingProfile tokenizer assets must be filename-sorted")
        object.__setattr__(self, "tokenizer_assets", assets)

        _require_version(
            "ChunkingProfile.transformers_version", self.transformers_version
        )
        _require_version("ChunkingProfile.tokenizers_version", self.tokenizers_version)
        _require_version(
            "ChunkingProfile.sentencepiece_version", self.sentencepiece_version
        )
