from __future__ import annotations

import hashlib
import re

import pytest

from knowledgenexus.foundation.domain.rules import ChunkIdGenerator


def _generate(
    *,
    source_system: str = "confluence",
    document_stable_key: str = "page:123",
    unit_key: str = "heading:intro",
    normalized_text: str = "Intro\n\nBody text",
) -> str:
    return ChunkIdGenerator.generate_chunk_id(
        source_system=source_system,
        document_stable_key=document_stable_key,
        unit_key=unit_key,
        normalized_text=normalized_text,
    )


def test_same_inputs_produce_same_chunk_id() -> None:
    assert _generate() == _generate()


def test_different_normalized_text_changes_chunk_id() -> None:
    assert _generate(normalized_text="alpha") != _generate(normalized_text="beta")


def test_different_unit_key_changes_chunk_id() -> None:
    assert _generate(unit_key="section:1") != _generate(unit_key="section:2")


def test_different_document_stable_key_changes_chunk_id() -> None:
    assert _generate(document_stable_key="page:1") != _generate(document_stable_key="page:2")


def test_output_starts_with_chunk_source_system_prefix() -> None:
    assert _generate(source_system="confluence").startswith("chunk:confluence:")


def test_digest_part_is_16_lowercase_hex_chars() -> None:
    chunk_id = _generate()
    digest_part = chunk_id.rsplit(":", 1)[-1]

    assert re.fullmatch(r"[0-9a-f]{16}", digest_part)


def test_generated_value_matches_sha256_digest_contract() -> None:
    document_stable_key = "page:123"
    unit_key = "heading:intro"
    normalized_text = "Intro\n\nBody text"
    digest_input = f"{document_stable_key}\x1f{unit_key}\x1f{normalized_text}"
    expected_hex16 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]

    assert _generate(
        document_stable_key=document_stable_key,
        unit_key=unit_key,
        normalized_text=normalized_text,
    ) == f"chunk:confluence:{expected_hex16}"


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="normalized_text expects str"):
        ChunkIdGenerator.generate_chunk_id(
            source_system="confluence",
            document_stable_key="page:123",
            unit_key="heading:intro",
            normalized_text=123,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field_name",
    ["source_system", "document_stable_key", "unit_key", "normalized_text"],
)
def test_empty_string_input_fails(field_name: str) -> None:
    values = {
        "source_system": "confluence",
        "document_stable_key": "page:123",
        "unit_key": "heading:intro",
        "normalized_text": "Intro\n\nBody text",
    }
    values[field_name] = ""

    with pytest.raises(ValueError, match=f"{field_name} must not be empty"):
        ChunkIdGenerator.generate_chunk_id(**values)
