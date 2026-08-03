from __future__ import annotations

from dataclasses import dataclass, field

from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)


def _require_exact_int(field_name: str, value: object) -> None:
    if type(value) is not int:
        raise TypeError(f"{field_name} expects an integer")


@dataclass(frozen=True)
class ConfluenceInventoryWindow:
    """One validated, normalized descendants response window."""

    items: tuple[ConfluencePageMetadata, ...]
    start: int
    limit: int
    size: int
    total_size: int
    next_start: int | None = field(init=False)
    is_terminal: bool = field(init=False)

    def __post_init__(self) -> None:
        try:
            copied_items = tuple(self.items)
        except TypeError:
            raise TypeError("items expects an iterable of page metadata") from None
        if not all(isinstance(item, ConfluencePageMetadata) for item in copied_items):
            raise TypeError("items expects ConfluencePageMetadata entries")

        for field_name, value in (
            ("start", self.start),
            ("limit", self.limit),
            ("size", self.size),
            ("total_size", self.total_size),
        ):
            _require_exact_int(field_name, value)
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.size < 0:
            raise ValueError("size must be non-negative")
        if self.total_size < 0:
            raise ValueError("total_size must be non-negative")
        if self.size != len(copied_items):
            raise ValueError("size must equal the number of items")
        if self.size > self.limit:
            raise ValueError("size must not exceed limit")
        if self.total_size < self.start + self.size:
            raise ValueError("total_size must cover the current window")
        if self.start < self.total_size and self.size == 0:
            raise ValueError("a non-terminal window must advance")

        object.__setattr__(self, "items", copied_items)
        terminal = self.start + self.size >= self.total_size
        object.__setattr__(self, "is_terminal", terminal)
        object.__setattr__(self, "next_start", None if terminal else self.start + self.size)
