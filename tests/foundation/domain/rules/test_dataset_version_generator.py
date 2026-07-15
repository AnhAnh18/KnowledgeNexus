from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo

import pytest

from knowledgenexus.foundation.domain.rules import DatasetVersionGenerator


def test_exact_utc_formatting() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=timezone.utc)

    assert (
        DatasetVersionGenerator.generate(instant=instant)
        == "v20260713-093015-123456Z"
    )


def test_zero_microseconds_are_six_digits() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, tzinfo=timezone.utc)

    assert (
        DatasetVersionGenerator.generate(instant=instant)
        == "v20260713-093015-000000Z"
    )


def test_same_instant_produces_same_dataset_version() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=timezone.utc)

    assert DatasetVersionGenerator.generate(
        instant=instant
    ) == DatasetVersionGenerator.generate(instant=instant)


def test_microseconds_distinguish_dataset_versions() -> None:
    first = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=timezone.utc)
    second = datetime(2026, 7, 13, 9, 30, 15, 123457, tzinfo=timezone.utc)

    assert DatasetVersionGenerator.generate(
        instant=first
    ) != DatasetVersionGenerator.generate(instant=second)


def test_non_utc_timezone_is_converted_to_utc() -> None:
    vietnam_time = timezone(timedelta(hours=7))
    instant = datetime(2026, 7, 13, 16, 30, 15, 123456, tzinfo=vietnam_time)

    assert (
        DatasetVersionGenerator.generate(instant=instant)
        == "v20260713-093015-123456Z"
    )


def test_utc_conversion_can_move_to_previous_calendar_day() -> None:
    plus_two = timezone(timedelta(hours=2))
    instant = datetime(2026, 7, 14, 0, 15, 30, 654321, tzinfo=plus_two)

    assert (
        DatasetVersionGenerator.generate(instant=instant)
        == "v20260713-221530-654321Z"
    )


def test_utc_conversion_can_move_to_next_calendar_day() -> None:
    minus_two = timezone(timedelta(hours=-2))
    instant = datetime(2026, 7, 13, 23, 45, 30, 654321, tzinfo=minus_two)

    assert (
        DatasetVersionGenerator.generate(instant=instant)
        == "v20260714-014530-654321Z"
    )


def test_dataset_versions_sort_lexicographically_by_instant() -> None:
    first = datetime(2026, 7, 13, 9, 30, 15, 1, tzinfo=timezone.utc)
    second = datetime(2026, 7, 13, 9, 30, 15, 2, tzinfo=timezone.utc)
    third = datetime(2026, 7, 13, 9, 30, 16, 0, tzinfo=timezone.utc)

    assert (
        DatasetVersionGenerator.generate(instant=first)
        < DatasetVersionGenerator.generate(instant=second)
        < DatasetVersionGenerator.generate(instant=third)
    )


def test_dataset_version_pattern_and_windows_safe_characters() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=timezone.utc)
    dataset_version = DatasetVersionGenerator.generate(instant=instant)

    assert re.fullmatch(r"v[0-9]{8}-[0-9]{6}-[0-9]{6}Z", dataset_version)
    assert ":" not in dataset_version
    assert "/" not in dataset_version
    assert "\\" not in dataset_version
    assert not any(character.isspace() for character in dataset_version)


def test_naive_datetime_is_rejected() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, 123456)

    with pytest.raises(ValueError, match="must be timezone-aware"):
        DatasetVersionGenerator.generate(instant=instant)


def test_datetime_with_none_utcoffset_is_rejected() -> None:
    instant = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=_NoneOffsetTz())

    with pytest.raises(ValueError, match="must be timezone-aware"):
        DatasetVersionGenerator.generate(instant=instant)


@pytest.mark.parametrize(
    "instant",
    [
        "2026-07-13T09:30:15Z",
        date(2026, 7, 13),
        123,
        None,
    ],
)
def test_non_datetime_input_is_rejected(instant: object) -> None:
    with pytest.raises(TypeError, match="instant expects datetime"):
        DatasetVersionGenerator.generate(instant=instant)  # type: ignore[arg-type]


def test_equivalent_instants_with_different_offsets_produce_same_version() -> None:
    utc_instant = datetime(2026, 7, 13, 9, 30, 15, 123456, tzinfo=timezone.utc)
    plus_seven_instant = datetime(
        2026,
        7,
        13,
        16,
        30,
        15,
        123456,
        tzinfo=timezone(timedelta(hours=7)),
    )

    assert DatasetVersionGenerator.generate(
        instant=utc_instant
    ) == DatasetVersionGenerator.generate(instant=plus_seven_instant)


class _NoneOffsetTz(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None
