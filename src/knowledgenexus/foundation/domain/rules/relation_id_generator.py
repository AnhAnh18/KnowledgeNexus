from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.rules.hashing_constants import (
    HASH_ENCODING,
    ID_DIGEST_HEX_LENGTH,
    ID_FIELD_SEPARATOR,
)


class RelationIdGenerator:
    """Deterministic relation ID generation for Foundation relation records."""

    @classmethod
    def generate_relation_id(
        cls,
        source_id: str,
        relation_type: str,
        target_id: str,
    ) -> str:
        cls._require_non_empty_string("source_id", source_id)
        cls._require_non_empty_string("relation_type", relation_type)
        cls._require_non_empty_string("target_id", target_id)

        digest_input = ID_FIELD_SEPARATOR.join([source_id, relation_type, target_id])
        hex16 = hashlib.sha256(digest_input.encode(HASH_ENCODING)).hexdigest()[
            :ID_DIGEST_HEX_LENGTH
        ]

        return f"rel:{hex16}"

    @staticmethod
    def _require_non_empty_string(field_name: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"RelationIdGenerator.{field_name} expects str")
        if value == "":
            raise ValueError(f"RelationIdGenerator.{field_name} must not be empty")
