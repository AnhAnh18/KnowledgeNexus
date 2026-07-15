from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.rules.hashing_constants import (
    HASH_ENCODING,
    ID_DIGEST_HEX_LENGTH,
    ID_FIELD_SEPARATOR,
)


class TombstoneIdGenerator:
    """Deterministic tombstone ID generation for Foundation tombstone records."""

    @classmethod
    def generate_tombstone_id(
        cls,
        entity_type: str,
        entity_id: str,
        reason: str,
        dataset_version: str,
    ) -> str:
        cls._require_non_empty_string("entity_type", entity_type)
        cls._require_non_empty_string("entity_id", entity_id)
        cls._require_non_empty_string("reason", reason)
        cls._require_non_empty_string("dataset_version", dataset_version)

        digest_input = ID_FIELD_SEPARATOR.join(
            [entity_type, entity_id, reason, dataset_version]
        )
        hex16 = hashlib.sha256(digest_input.encode(HASH_ENCODING)).hexdigest()[
            :ID_DIGEST_HEX_LENGTH
        ]

        return f"tomb:{hex16}"

    @staticmethod
    def _require_non_empty_string(field_name: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"TombstoneIdGenerator.{field_name} expects str")
        if value == "":
            raise ValueError(f"TombstoneIdGenerator.{field_name} must not be empty")
