from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.rules import (
    ChunkIdGenerator,
    ContentHasher,
    TextNormalizationRules,
)


def _chunk_id(normalized_text: str) -> str:
    return ChunkIdGenerator.generate_chunk_id(
        source_system="confluence",
        document_stable_key="page:123",
        unit_key="heading:intro",
        normalized_text=normalized_text,
    )


def test_line_ending_variants_normalize_hash_and_chunk_id_the_same() -> None:
    crlf_text = "Heading\r\n\r\nBody line\r\n  code line"
    lf_text = "Heading\n\nBody line\n  code line"

    normalized_crlf = TextNormalizationRules.normalize_text(crlf_text)
    normalized_lf = TextNormalizationRules.normalize_text(lf_text)

    assert normalized_crlf == normalized_lf
    assert ContentHasher.hash_text(normalized_crlf) == ContentHasher.hash_text(normalized_lf)
    assert _chunk_id(normalized_crlf) == _chunk_id(normalized_lf)


def test_real_content_change_after_normalization_changes_hash_and_chunk_id() -> None:
    original = TextNormalizationRules.normalize_text("Heading\n\nOriginal body")
    changed = TextNormalizationRules.normalize_text("Heading\n\nChanged body")

    assert original != changed
    assert ContentHasher.hash_text(original) != ContentHasher.hash_text(changed)
    assert _chunk_id(original) != _chunk_id(changed)


def test_chunk_id_generator_uses_passed_text_without_internal_normalization() -> None:
    raw_text = "Heading\r\nBody  "
    normalized_text = TextNormalizationRules.normalize_text(raw_text)

    raw_chunk_id = _chunk_id(raw_text)
    normalized_chunk_id = _chunk_id(normalized_text)

    assert raw_text != normalized_text
    assert raw_chunk_id != normalized_chunk_id

    expected_raw_digest = hashlib.sha256(
        f"page:123\x1fheading:intro\x1f{raw_text}".encode("utf-8")
    ).hexdigest()[:16]
    assert raw_chunk_id == f"chunk:confluence:{expected_raw_digest}"
