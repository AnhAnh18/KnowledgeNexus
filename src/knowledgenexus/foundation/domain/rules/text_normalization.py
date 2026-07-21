from __future__ import annotations

import re
import unicodedata


_THREE_OR_MORE_NEWLINES = re.compile(r"\n{3,}")


class TextNormalizationRules:
    """Deterministic text normalization before hashing, counting, and IDs."""

    @staticmethod
    def normalize_text(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("TextNormalizationRules.normalize_text expects text to be str")

        normalized = unicodedata.normalize("NFC", text)
        lines = normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = [line.rstrip() for line in lines]
        normalized = "\n".join(lines)
        normalized = _THREE_OR_MORE_NEWLINES.sub("\n\n", normalized)
        return normalized.strip("\n")
