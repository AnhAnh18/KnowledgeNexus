from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.rules.hashing_constants import HASH_ENCODING


class ContentHasher:
    """Deterministic SHA-256 hashing for already-normalized content text."""

    @staticmethod
    def hash_text(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("ContentHasher.hash_text expects text to be str")

        return hashlib.sha256(text.encode(HASH_ENCODING)).hexdigest()
