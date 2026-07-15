from __future__ import annotations


class TextNormalizationRules:
    """Deterministic text normalization before hashing, counting, and IDs."""

    @staticmethod
    def normalize_text(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("TextNormalizationRules.normalize_text expects text to be str")

        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = [line.rstrip() for line in lines]

        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        collapsed_lines: list[str] = []
        blank_count = 0
        for line in lines:
            if not line:
                blank_count += 1
                if blank_count <= 2:
                    collapsed_lines.append(line)
                continue

            blank_count = 0
            collapsed_lines.append(line)

        return "\n".join(collapsed_lines)
