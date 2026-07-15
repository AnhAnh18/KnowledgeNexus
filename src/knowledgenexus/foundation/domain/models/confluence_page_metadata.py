from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


def _require_non_empty_string(field_name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} expects str")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_string(field_name: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} expects str or None")


def _copy_ordered_string_tuple(field_name: str, values: Any) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} expects an ordered collection of strings")
    copied_values = tuple(values)
    if not all(isinstance(value, str) for value in copied_values):
        raise TypeError(f"{field_name} expects strings")
    return copied_values


def _copy_sorted_unique_string_tuple(
    field_name: str,
    values: Any,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} expects a collection of strings")
    copied_values = tuple(values)
    if not all(isinstance(value, str) for value in copied_values):
        raise TypeError(f"{field_name} expects strings")
    return tuple(sorted(set(copied_values)))


@dataclass(frozen=True)
class ConfluencePageMetadata:
    page_id: str
    title: str
    space_key: str
    parent_page_id: str | None = None
    ancestor_page_ids: tuple[str, ...] = ()
    ancestor_titles: tuple[str, ...] = ()
    updated_at: str | None = None
    source_version: str | None = None
    labels: tuple[str, ...] = ()
    attachment_count: int | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string("ConfluencePageMetadata.page_id", self.page_id)
        _require_non_empty_string("ConfluencePageMetadata.title", self.title)
        _require_non_empty_string("ConfluencePageMetadata.space_key", self.space_key)
        _require_optional_string(
            "ConfluencePageMetadata.parent_page_id", self.parent_page_id
        )
        _require_optional_string("ConfluencePageMetadata.updated_at", self.updated_at)
        _require_optional_string(
            "ConfluencePageMetadata.source_version", self.source_version
        )

        ancestor_page_ids = _copy_ordered_string_tuple(
            "ConfluencePageMetadata.ancestor_page_ids", self.ancestor_page_ids
        )
        ancestor_titles = _copy_ordered_string_tuple(
            "ConfluencePageMetadata.ancestor_titles", self.ancestor_titles
        )
        labels = _copy_sorted_unique_string_tuple(
            "ConfluencePageMetadata.labels", self.labels
        )

        if self.attachment_count is not None:
            if isinstance(self.attachment_count, bool) or not isinstance(
                self.attachment_count, int
            ):
                raise TypeError(
                    "ConfluencePageMetadata.attachment_count expects an integer or None"
                )
            if self.attachment_count < 0:
                raise ValueError(
                    "ConfluencePageMetadata.attachment_count must be non-negative"
                )

        object.__setattr__(self, "ancestor_page_ids", ancestor_page_ids)
        object.__setattr__(self, "ancestor_titles", ancestor_titles)
        object.__setattr__(self, "labels", labels)
