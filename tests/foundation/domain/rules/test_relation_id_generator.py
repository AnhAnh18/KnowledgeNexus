from __future__ import annotations

import hashlib
import re

import pytest

from knowledgenexus.foundation.domain.rules import RelationIdGenerator


def _generate(
    *,
    source_id: str = "chunk:confluence:source1234",
    relation_type: str = "references",
    target_id: str = "chunk:confluence:target5678",
) -> str:
    return RelationIdGenerator.generate_relation_id(
        source_id=source_id,
        relation_type=relation_type,
        target_id=target_id,
    )


def test_same_inputs_produce_same_relation_id() -> None:
    assert _generate() == _generate()


def test_different_source_id_changes_relation_id() -> None:
    assert _generate(source_id="source:1") != _generate(source_id="source:2")


def test_different_relation_type_changes_relation_id() -> None:
    assert _generate(relation_type="references") != _generate(relation_type="mentions")


def test_different_target_id_changes_relation_id() -> None:
    assert _generate(target_id="target:1") != _generate(target_id="target:2")


def test_output_starts_with_rel_prefix() -> None:
    assert _generate().startswith("rel:")


def test_digest_part_is_16_lowercase_hex_chars() -> None:
    relation_id = _generate()
    digest_part = relation_id.removeprefix("rel:")

    assert re.fullmatch(r"[0-9a-f]{16}", digest_part)


def test_generated_value_matches_sha256_digest_contract() -> None:
    source_id = "chunk:confluence:source1234"
    relation_type = "references"
    target_id = "chunk:confluence:target5678"
    digest_input = f"{source_id}\x1f{relation_type}\x1f{target_id}"
    expected_hex16 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]

    assert _generate(
        source_id=source_id,
        relation_type=relation_type,
        target_id=target_id,
    ) == f"rel:{expected_hex16}"


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="target_id expects str"):
        RelationIdGenerator.generate_relation_id(
            source_id="chunk:source",
            relation_type="references",
            target_id=123,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("field_name", ["source_id", "relation_type", "target_id"])
def test_empty_string_input_fails(field_name: str) -> None:
    values = {
        "source_id": "chunk:source",
        "relation_type": "references",
        "target_id": "chunk:target",
    }
    values[field_name] = ""

    with pytest.raises(ValueError, match=f"{field_name} must not be empty"):
        RelationIdGenerator.generate_relation_id(**values)
