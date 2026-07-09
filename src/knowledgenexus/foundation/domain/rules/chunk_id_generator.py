from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.rules.hashing_constants import (
    HASH_ENCODING,
    ID_DIGEST_HEX_LENGTH,
    ID_FIELD_SEPARATOR,
)


class ChunkIdGenerator:
    """Deterministic chunk ID generation for already-normalized chunk text."""

    @classmethod
    def generate_chunk_id(
        cls,
        source_system: str,
        document_stable_key: str,
        unit_key: str,
        normalized_text: str,
    ) -> str:
        cls._require_non_empty_string("source_system", source_system)
        cls._require_non_empty_string("document_stable_key", document_stable_key)
        cls._require_non_empty_string("unit_key", unit_key)
        cls._require_non_empty_string("normalized_text", normalized_text)

        digest_input = ID_FIELD_SEPARATOR.join(
            [document_stable_key, unit_key, normalized_text]
        )
        hex16 = hashlib.sha256(digest_input.encode(HASH_ENCODING)).hexdigest()[
            :ID_DIGEST_HEX_LENGTH
        ]

        return f"chunk:{source_system}:{hex16}"

    @staticmethod
    def _require_non_empty_string(field_name: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"ChunkIdGenerator.{field_name} expects str")
        if value == "":
            raise ValueError(f"ChunkIdGenerator.{field_name} must not be empty")
