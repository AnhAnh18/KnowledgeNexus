from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from knowledgenexus.foundation.domain.models import ChunkingProfile, TokenizerAsset


def _profile() -> ChunkingProfile:
    revision = "5617a9f61b028005a4858fdac845db406aefb181"
    repository = "https://huggingface.co/BAAI/bge-m3"
    return ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=96,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository=repository,
        tokenizer_revision=revision,
        observed_license="MIT",
        provenance_url=f"{repository}/tree/{revision}",
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17_098_108,
                sha256=(
                    "21106b6d7dab2952c1d496fb21d5dc9d"
                    "b75c28ed361a05f5020bbba27810dd08"
                ),
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )


def test_profile_is_immutable() -> None:
    profile = _profile()

    with pytest.raises(FrozenInstanceError):
        profile.target_tokens = 451  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("chunker_version", "1.1.0"),
        ("profile_status", "benchmark_complete"),
        ("active_profile", "large"),
        ("model_name", "fixture/model"),
        ("tokenizer_name", "fixture/tokenizer"),
        ("tokenizer_family", "WordPiece"),
    ],
)
def test_profile_rejects_identity_drift(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match="active contract"):
        replace(_profile(), **{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("minimum_tokens", 451),
        ("target_tokens", 1001),
        ("hard_maximum_tokens", 8192),
        ("overlap_tokens", 450),
        ("code_window_target_tokens", 1001),
        ("code_window_overlap_lines", 40),
    ],
)
def test_profile_rejects_invalid_budget_relationships(
    field_name: str, value: int
) -> None:
    with pytest.raises(ValueError):
        replace(_profile(), **{field_name: value})


def test_profile_rejects_unordered_or_duplicate_assets() -> None:
    profile = _profile()
    second = TokenizerAsset(
        filename="a.json",
        byte_size=1,
        sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="filename-sorted"):
        replace(profile, tokenizer_assets=(profile.tokenizer_assets[0], second))
    with pytest.raises(ValueError, match="unique"):
        replace(profile, tokenizer_assets=profile.tokenizer_assets * 2)


@pytest.mark.parametrize("filename", ["", "..", "nested/tokenizer.json", "..\\x"])
def test_tokenizer_asset_rejects_non_plain_filename(filename: str) -> None:
    with pytest.raises(ValueError, match="plain file name"):
        TokenizerAsset(filename=filename, byte_size=1, sha256="0" * 64)


def test_tokenizer_asset_rejects_invalid_hash_or_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        TokenizerAsset(filename="tokenizer.json", byte_size=0, sha256="0" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        TokenizerAsset(filename="tokenizer.json", byte_size=1, sha256="A" * 64)
