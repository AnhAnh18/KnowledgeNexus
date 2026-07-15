from __future__ import annotations

import hashlib
import re

import pytest

from knowledgenexus.foundation.domain.rules import TombstoneIdGenerator


def _generate(
    *,
    entity_type: str = "chunk",
    entity_id: str = "chunk:confluence:abc123",
    reason: str = "content_updated",
    dataset_version: str = "2026-07-09T10-00-00Z",
) -> str:
    return TombstoneIdGenerator.generate_tombstone_id(
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        dataset_version=dataset_version,
    )


def test_same_inputs_produce_same_tombstone_id() -> None:
    assert _generate() == _generate()


def test_different_entity_type_changes_tombstone_id() -> None:
    assert _generate(entity_type="chunk") != _generate(entity_type="document")


def test_different_entity_id_changes_tombstone_id() -> None:
    assert _generate(entity_id="chunk:1") != _generate(entity_id="chunk:2")


def test_different_reason_changes_tombstone_id() -> None:
    assert _generate(reason="content_updated") != _generate(reason="moved_out_of_scope")


def test_different_dataset_version_changes_tombstone_id() -> None:
    assert _generate(dataset_version="v1") != _generate(dataset_version="v2")


def test_output_starts_with_tomb_prefix() -> None:
    assert _generate().startswith("tomb:")


def test_digest_part_is_16_lowercase_hex_chars() -> None:
    tombstone_id = _generate()
    digest_part = tombstone_id.removeprefix("tomb:")

    assert re.fullmatch(r"[0-9a-f]{16}", digest_part)


def test_generated_value_matches_sha256_digest_contract() -> None:
    entity_type = "chunk"
    entity_id = "chunk:confluence:abc123"
    reason = "content_updated"
    dataset_version = "2026-07-09T10-00-00Z"
    digest_input = f"{entity_type}\x1f{entity_id}\x1f{reason}\x1f{dataset_version}"
    expected_hex16 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]

    assert _generate(
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        dataset_version=dataset_version,
    ) == f"tomb:{expected_hex16}"


@pytest.mark.parametrize(
    "field_name",
    ["entity_type", "entity_id", "reason", "dataset_version"],
)
def test_non_string_input_fails(field_name: str) -> None:
    values = {
        "entity_type": "chunk",
        "entity_id": "chunk:confluence:abc123",
        "reason": "source_deleted",
        "dataset_version": "2026-07-09T10-00-00Z",
    }
    values[field_name] = 123  # type: ignore[assignment]

    with pytest.raises(TypeError, match=f"{field_name} expects str"):
        TombstoneIdGenerator.generate_tombstone_id(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    ["entity_type", "entity_id", "reason", "dataset_version"],
)
def test_empty_string_input_fails(field_name: str) -> None:
    values = {
        "entity_type": "chunk",
        "entity_id": "chunk:confluence:abc123",
        "reason": "source_deleted",
        "dataset_version": "2026-07-09T10-00-00Z",
    }
    values[field_name] = ""

    with pytest.raises(ValueError, match=f"{field_name} must not be empty"):
        TombstoneIdGenerator.generate_tombstone_id(**values)
