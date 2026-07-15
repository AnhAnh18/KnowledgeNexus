from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_INVENTORY_PAGE_SIZE = 50


def _require_non_empty_string(field_name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} expects str")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_string(field_name: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} expects str or None")


def _copy_collection(field_name: str, values: Any) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} expects a collection")
    return tuple(values)


@dataclass(frozen=True)
class ConfluenceIncludeRoot:
    page_id: str
    name: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string("ConfluenceIncludeRoot.page_id", self.page_id)
        _require_optional_string("ConfluenceIncludeRoot.name", self.name)


@dataclass(frozen=True)
class ConfluenceExcludeSubtree:
    page_id: str
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string("ConfluenceExcludeSubtree.page_id", self.page_id)
        _require_optional_string("ConfluenceExcludeSubtree.reason", self.reason)


@dataclass(frozen=True)
class ConfluenceSourceConfig:
    source_id: str
    space_key: str
    include_roots: tuple[ConfluenceIncludeRoot, ...]
    exclude_subtrees: tuple[ConfluenceExcludeSubtree, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    page_size: int = DEFAULT_INVENTORY_PAGE_SIZE

    def __post_init__(self) -> None:
        _require_non_empty_string("ConfluenceSourceConfig.source_id", self.source_id)
        _require_non_empty_string("ConfluenceSourceConfig.space_key", self.space_key)

        include_roots = _copy_collection(
            "ConfluenceSourceConfig.include_roots", self.include_roots
        )
        exclude_subtrees = _copy_collection(
            "ConfluenceSourceConfig.exclude_subtrees", self.exclude_subtrees
        )
        include_keywords = _copy_collection(
            "ConfluenceSourceConfig.include_keywords", self.include_keywords
        )
        exclude_keywords = _copy_collection(
            "ConfluenceSourceConfig.exclude_keywords", self.exclude_keywords
        )

        if not include_roots:
            raise ValueError("ConfluenceSourceConfig.include_roots must not be empty")
        if not all(isinstance(root, ConfluenceIncludeRoot) for root in include_roots):
            raise TypeError(
                "ConfluenceSourceConfig.include_roots expects ConfluenceIncludeRoot entries"
            )
        if not all(
            isinstance(subtree, ConfluenceExcludeSubtree)
            for subtree in exclude_subtrees
        ):
            raise TypeError(
                "ConfluenceSourceConfig.exclude_subtrees expects "
                "ConfluenceExcludeSubtree entries"
            )
        if not all(isinstance(keyword, str) for keyword in include_keywords):
            raise TypeError("ConfluenceSourceConfig.include_keywords expects strings")
        if not all(isinstance(keyword, str) for keyword in exclude_keywords):
            raise TypeError("ConfluenceSourceConfig.exclude_keywords expects strings")

        include_ids = [root.page_id for root in include_roots]
        exclude_ids = [subtree.page_id for subtree in exclude_subtrees]
        if len(include_ids) != len(set(include_ids)):
            raise ValueError("ConfluenceSourceConfig include-root page IDs must be unique")
        if len(exclude_ids) != len(set(exclude_ids)):
            raise ValueError(
                "ConfluenceSourceConfig excluded-subtree page IDs must be unique"
            )

        overlap = set(include_ids).intersection(exclude_ids)
        if overlap:
            raise ValueError(
                "ConfluenceSourceConfig include/exclude page IDs must not overlap: "
                f"{sorted(overlap)}"
            )

        if isinstance(self.page_size, bool) or not isinstance(self.page_size, int):
            raise TypeError("ConfluenceSourceConfig.page_size expects an integer")
        if self.page_size <= 0:
            raise ValueError("ConfluenceSourceConfig.page_size must be positive")

        object.__setattr__(self, "include_roots", include_roots)
        object.__setattr__(self, "exclude_subtrees", exclude_subtrees)
        object.__setattr__(self, "include_keywords", include_keywords)
        object.__setattr__(self, "exclude_keywords", exclude_keywords)
