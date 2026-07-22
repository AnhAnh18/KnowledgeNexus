from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class CharacterSpan:
    """One tokenizer-reported half-open span in Python character indexes."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise TypeError("CharacterSpan.start expects an integer")
        if isinstance(self.end, bool) or not isinstance(self.end, int):
            raise TypeError("CharacterSpan.end expects an integer")
        if self.start < 0:
            raise ValueError("CharacterSpan.start must be non-negative")
        if self.end <= self.start:
            raise ValueError("CharacterSpan.end must be greater than start")


@dataclass(frozen=True)
class TokenizationResult:
    """Raw ordered token spans; these are not automatically safe split points."""

    spans: tuple[CharacterSpan, ...]

    def __post_init__(self) -> None:
        if isinstance(self.spans, (str, bytes)):
            raise TypeError("TokenizationResult.spans expects a collection")
        spans = tuple(self.spans)
        if not all(isinstance(span, CharacterSpan) for span in spans):
            raise TypeError(
                "TokenizationResult.spans expects CharacterSpan entries"
            )

        previous_start = -1
        previous_end = -1
        for span in spans:
            if span.start < previous_start or span.end < previous_end:
                raise ValueError(
                    "TokenizationResult spans must have non-decreasing starts and ends"
                )
            previous_start = span.start
            previous_end = span.end

        object.__setattr__(self, "spans", spans)

    @property
    def token_count(self) -> int:
        return len(self.spans)
