from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from knowledgenexus.foundation.domain.models import CharacterSpan, TokenizationResult


def test_character_span_is_immutable_and_half_open() -> None:
    span = CharacterSpan(start=1, end=3)

    assert (span.start, span.end) == (1, 3)
    with pytest.raises(FrozenInstanceError):
        span.start = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("start", "end", "error_type"),
    [
        (True, 1, TypeError),
        (0, False, TypeError),
        (-1, 1, ValueError),
        (0, 0, ValueError),
        (2, 1, ValueError),
    ],
)
def test_character_span_rejects_invalid_bounds(
    start: object, end: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        CharacterSpan(start=start, end=end)  # type: ignore[arg-type]


def test_result_copies_collection_and_derives_count() -> None:
    source = [CharacterSpan(0, 1), CharacterSpan(1, 3)]

    result = TokenizationResult(spans=source)  # type: ignore[arg-type]
    source.clear()

    assert result.spans == (CharacterSpan(0, 1), CharacterSpan(1, 3))
    assert result.token_count == 2


def test_result_accepts_overlapping_and_equal_spans() -> None:
    result = TokenizationResult(
        spans=(
            CharacterSpan(0, 1),
            CharacterSpan(0, 1),
            CharacterSpan(1, 2),
        )
    )

    assert result.token_count == 3


@pytest.mark.parametrize(
    "spans",
    [
        (CharacterSpan(1, 2), CharacterSpan(0, 3)),
        (CharacterSpan(0, 3), CharacterSpan(1, 2)),
    ],
)
def test_result_rejects_decreasing_starts_or_ends(
    spans: tuple[CharacterSpan, ...],
) -> None:
    with pytest.raises(ValueError, match="non-decreasing"):
        TokenizationResult(spans=spans)


def test_result_rejects_scalar_or_non_span_entries() -> None:
    with pytest.raises(TypeError, match="collection"):
        TokenizationResult(spans="not-spans")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="CharacterSpan"):
        TokenizationResult(spans=((0, 1),))  # type: ignore[arg-type]
