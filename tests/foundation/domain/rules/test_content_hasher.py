from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.domain.rules import ContentHasher


def test_same_input_gives_same_hash() -> None:
    text = "Heading\n\nBody text"

    assert ContentHasher.hash_text(text) == ContentHasher.hash_text(text)


def test_different_input_gives_different_hash() -> None:
    assert ContentHasher.hash_text("alpha") != ContentHasher.hash_text("beta")


def test_output_length_is_64() -> None:
    assert len(ContentHasher.hash_text("content")) == 64


def test_output_matches_sha256_utf8_hexdigest() -> None:
    text = "SVMC text with symbols: -> [] {}"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()

    assert ContentHasher.hash_text(text) == expected


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="expects text to be str"):
        ContentHasher.hash_text(123)  # type: ignore[arg-type]
