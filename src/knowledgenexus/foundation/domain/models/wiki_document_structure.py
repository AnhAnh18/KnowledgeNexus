from __future__ import annotations

from dataclasses import dataclass

# These are internal Foundation domain models, not export records. They carry
# page content, so ``repr`` is disabled to keep prose, code, and table text out
# of tracebacks and logs (sanitization requirement). Equality and hashing stay
# enabled by the frozen dataclass so the same input yields an exactly equal,
# immutable structure.


@dataclass(frozen=True, repr=False)
class WikiProseBlock:
    """A run of prose (paragraphs, lists, blockquotes, rules, h4-h6, links)."""

    text: str
    source_ordinal: int


@dataclass(frozen=True, repr=False)
class WikiTableBlock:
    """A rectangular Markdown table recognized from a valid header/separator."""

    raw_text: str
    header_line: str
    separator_line: str
    row_lines: tuple[str, ...]
    column_count: int
    source_ordinal: int


@dataclass(frozen=True, repr=False)
class WikiCodeBlock:
    """A fenced code block preserved verbatim between its backtick fences."""

    raw_text: str
    fence_marker: str
    info_string: str
    body_lines: tuple[str, ...]
    source_ordinal: int


WikiBlock = WikiProseBlock | WikiTableBlock | WikiCodeBlock


@dataclass(frozen=True, repr=False)
class WikiSection:
    """One structural section: a heading path plus its ordered blocks.

    ``heading_level`` and ``heading_source_line`` are ``None`` for the implicit
    preamble section that holds content appearing before the first structural
    heading. ``heading_path`` always starts with the page title.
    """

    heading_path: tuple[str, ...]
    heading_level: int | None
    heading_source_line: int | None
    source_ordinal: int
    blocks: tuple[WikiBlock, ...]


@dataclass(frozen=True, repr=False)
class WikiDocumentStructure:
    """One immutable wiki document: a page title and its ordered sections."""

    page_title: str
    sections: tuple[WikiSection, ...]
