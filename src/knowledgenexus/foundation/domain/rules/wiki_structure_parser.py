from __future__ import annotations

import re

from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiCodeBlock,
    WikiDocumentStructure,
    WikiProseBlock,
    WikiSection,
    WikiTableBlock,
)
from knowledgenexus.foundation.domain.rules.text_normalization import (
    TextNormalizationRules,
)

# Sanitized failure categories. A category is the only payload of the raised
# error; no page title, heading, prose, code, table content, identifier, path,
# or URL is ever included in the message.
CATEGORY_INVALID_PAGE_TITLE = "invalid_page_title"
CATEGORY_INVALID_NORMALIZED_TEXT = "invalid_normalized_text"
CATEGORY_NON_CANONICAL_NORMALIZED_TEXT = "non_canonical_normalized_text"
CATEGORY_EMPTY_STRUCTURAL_HEADING = "empty_structural_heading"
CATEGORY_UNCLOSED_CODE_FENCE = "unclosed_code_fence"
CATEGORY_STRUCTURAL_PARSE_FAILED = "structural_parse_failed"

# Any ATX heading line (1-6 hashes, then either end-of-line or space + label).
# The level decides whether it is structural (1-3) or prose (4-6). A line whose
# hashes are followed directly by a non-space character (``#tag``) or that has
# seven or more hashes does not match and stays prose.
_ATX_HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")

# An opening backtick code fence, optionally indented. M6C indents fenced code
# blocks that sit inside list items, so the fence is not anchored to column 0.
# Group 1 is the leading indent, group 2 the backtick run, group 3 the info
# string (which, for a backtick fence, may not itself contain a backtick).
_CODE_FENCE_OPEN = re.compile(r"^([ \t]*)(`{3,})([^`]*)$")

# A Markdown table separator cell, once surrounding spaces are removed. M6C emits
# separator cells as runs of three or more hyphens with no alignment colons, so a
# single/double hyphen or a colon cell is prose, not a table separator.
_SEPARATOR_CELL = re.compile(r"^-{3,}$")


class WikiStructureParseError(Exception):
    """A sanitized, category-tagged structural wiki parse failure."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class WikiStructureParser:
    """Parse approved M6C canonical Markdown into an immutable wiki structure.

    The parser is pure: no I/O, no network, no filesystem, no tokenizer. It does
    not budget, split, overlap, or otherwise chunk. It consumes an already
    canonical M6C body (NFC, LF, trailing-stripped, blank-collapsed) and never
    re-normalizes or mutates it.
    """

    @staticmethod
    def parse(*, page_title: object, normalized_body_text: object) -> WikiDocumentStructure:
        if not isinstance(page_title, str) or page_title.strip() == "":
            raise WikiStructureParseError(CATEGORY_INVALID_PAGE_TITLE)
        if not isinstance(normalized_body_text, str):
            raise WikiStructureParseError(CATEGORY_INVALID_NORMALIZED_TEXT)

        # Fail closed on non-canonical input without mutating it. The shared rule
        # implements CHUNKING_SPEC §2, identical to the M6C normalizer, so valid
        # M6C output is a fixed point and passes unchanged.
        if TextNormalizationRules.normalize_text(normalized_body_text) != normalized_body_text:
            raise WikiStructureParseError(CATEGORY_NON_CANONICAL_NORMALIZED_TEXT)

        if normalized_body_text == "":
            return WikiDocumentStructure(page_title=page_title, sections=())

        try:
            lines = normalized_body_text.split("\n")
            events = _scan_events(lines)
            sections = _assemble_sections(page_title, events)
            return _finalize(page_title, sections)
        except WikiStructureParseError:
            raise
        except Exception as exc:  # pragma: no cover - defensive, no content leaked
            raise WikiStructureParseError(CATEGORY_STRUCTURAL_PARSE_FAILED) from exc


# --------------------------------------------------------------------------
# Line scanner
# --------------------------------------------------------------------------

# Intermediate block tuples (built into frozen models with an ordinal later):
#   ("prose", text)
#   ("table", raw_text, header_line, separator_line, row_lines, column_count)
#   ("code", raw_text, fence_marker, info_string, body_lines)
# Intermediate events:
#   ("heading", level, label, source_line)
#   ("block", intermediate_block)


def _scan_events(lines: list[str]) -> list[tuple]:
    events: list[tuple] = []
    prose_buffer: list[str] = []

    def flush_prose() -> None:
        start = 0
        end = len(prose_buffer)
        while start < end and prose_buffer[start] == "":
            start += 1
        while end > start and prose_buffer[end - 1] == "":
            end -= 1
        if start < end:
            events.append(("block", ("prose", "\n".join(prose_buffer[start:end]))))
        prose_buffer.clear()

    index = 0
    total = len(lines)
    while index < total:
        line = lines[index]

        # 1. Active fenced code overrides every other recognition.
        fence_match = _CODE_FENCE_OPEN.match(line)
        if fence_match is not None:
            fence = fence_match.group(2)
            info_string = fence_match.group(3)
            body: list[str] = []
            cursor = index + 1
            closed = False
            while cursor < total:
                if _is_closing_fence(lines[cursor], fence):
                    closed = True
                    break
                body.append(lines[cursor])
                cursor += 1
            if not closed:
                raise WikiStructureParseError(CATEGORY_UNCLOSED_CODE_FENCE)
            flush_prose()
            raw_text = "\n".join(lines[index : cursor + 1])
            events.append(
                ("block", ("code", raw_text, fence, info_string, tuple(body)))
            )
            index = cursor + 1
            continue

        # 2. Structural h1-h3 headings.
        heading_match = _ATX_HEADING.match(line)
        if heading_match is not None:
            level = len(heading_match.group(1))
            if 1 <= level <= 3:
                label = (heading_match.group(2) or "").strip()
                if label == "":
                    raise WikiStructureParseError(CATEGORY_EMPTY_STRUCTURAL_HEADING)
                flush_prose()
                events.append(("heading", level, label, index + 1))
                index += 1
                continue
            # h4-h6 fall through to prose.

        # 3. A valid Markdown table.
        table = _try_table(lines, index)
        if table is not None:
            block, next_index = table
            flush_prose()
            events.append(("block", block))
            index = next_index
            continue

        # 4. Everything else is prose.
        prose_buffer.append(line)
        index += 1

    flush_prose()
    return events


def _is_closing_fence(candidate: str, fence: str) -> bool:
    # Leading indent is stripped as well as trailing space: M6C indents the
    # closing fence to match its (possibly indented) opening fence.
    stripped = candidate.strip()
    if stripped == "":
        return False
    fence_char = fence[0]
    if any(character != fence_char for character in stripped):
        return False
    return len(stripped) >= len(fence)


# --------------------------------------------------------------------------
# Table recognition
# --------------------------------------------------------------------------


def _try_table(lines: list[str], index: int) -> tuple[tuple, int] | None:
    total = len(lines)
    if index + 1 >= total:
        return None

    header = lines[index]
    separator = lines[index + 1]
    # Structural tables are unindented. An indented pipe/dash line belongs to a
    # surrounding list (prose); it is never promoted to a table. Indented lines
    # that are code appear only inside an already-open fence, handled earlier.
    if _is_indented(header) or _is_indented(separator):
        return None
    if _count_unescaped_pipes(header) < 1 or _count_unescaped_pipes(separator) < 1:
        return None

    separator_cells = _split_row_cells(separator)
    if not _is_separator_row(separator_cells):
        return None

    column_count = len(_split_row_cells(header))
    if column_count != len(separator_cells):
        return None

    rows: list[str] = []
    cursor = index + 2
    while cursor < total:
        candidate = lines[cursor]
        if candidate == "":
            break
        if _is_indented(candidate):
            break
        if _CODE_FENCE_OPEN.match(candidate) is not None:
            break
        heading_match = _ATX_HEADING.match(candidate)
        if heading_match is not None and 1 <= len(heading_match.group(1)) <= 3:
            break
        if _count_unescaped_pipes(candidate) < 1:
            break
        rows.append(candidate)
        cursor += 1

    # A table is recognized only when every collected row is rectangular. A
    # non-rectangular candidate is left entirely as prose (never repaired).
    for row in rows:
        if len(_split_row_cells(row)) != column_count:
            return None

    raw_text = "\n".join([header, separator, *rows])
    block = ("table", raw_text, header, separator, tuple(rows), column_count)
    return block, cursor


def _is_indented(line: str) -> bool:
    return line[:1] in (" ", "\t")


def _count_unescaped_pipes(line: str) -> int:
    count = 0
    index = 0
    length = len(line)
    while index < length:
        character = line[index]
        if character == "\\" and index + 1 < length:
            index += 2
            continue
        if character == "|":
            count += 1
        index += 1
    return count


def _split_row_cells(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if _ends_with_unescaped_pipe(text):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == "\\" and index + 1 < length:
            current.append(character)
            current.append(text[index + 1])
            index += 2
            continue
        if character == "|":
            cells.append("".join(current))
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    cells.append("".join(current))
    return cells


def _ends_with_unescaped_pipe(text: str) -> bool:
    if not text.endswith("|"):
        return False
    backslashes = 0
    index = len(text) - 2
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 0


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(_SEPARATOR_CELL.match(cell.strip()) is not None for cell in cells)


# --------------------------------------------------------------------------
# Section assembly
# --------------------------------------------------------------------------


def _assemble_sections(page_title: str, events: list[tuple]) -> list[dict]:
    sections: list[dict] = []
    stack: list[tuple[str, int]] = []

    current = _new_section((page_title,), None, None, is_preamble=True)

    def close(section: dict) -> None:
        if section["is_preamble"]:
            if section["blocks"]:
                sections.append(section)
        else:
            sections.append(section)

    for event in events:
        if event[0] == "heading":
            _, level, label, source_line = event
            close(current)
            while stack and stack[-1][1] >= level:
                stack.pop()
            stack.append((label, level))
            heading_path = (page_title,) + tuple(entry[0] for entry in stack)
            current = _new_section(
                heading_path, level, source_line, is_preamble=False
            )
        else:
            current["blocks"].append(event[1])

    close(current)
    return sections


def _new_section(
    heading_path: tuple[str, ...],
    heading_level: int | None,
    heading_source_line: int | None,
    *,
    is_preamble: bool,
) -> dict:
    return {
        "heading_path": heading_path,
        "heading_level": heading_level,
        "heading_source_line": heading_source_line,
        "blocks": [],
        "is_preamble": is_preamble,
    }


def _finalize(page_title: str, sections: list[dict]) -> WikiDocumentStructure:
    ordinal = 0
    built_sections: list[WikiSection] = []
    for section in sections:
        section_ordinal = ordinal
        ordinal += 1
        built_blocks: list[object] = []
        for block in section["blocks"]:
            built_blocks.append(_build_block(block, ordinal))
            ordinal += 1
        built_sections.append(
            WikiSection(
                heading_path=section["heading_path"],
                heading_level=section["heading_level"],
                heading_source_line=section["heading_source_line"],
                source_ordinal=section_ordinal,
                blocks=tuple(built_blocks),
            )
        )
    return WikiDocumentStructure(
        page_title=page_title, sections=tuple(built_sections)
    )


def _build_block(block: tuple, source_ordinal: int) -> object:
    kind = block[0]
    if kind == "prose":
        return WikiProseBlock(text=block[1], source_ordinal=source_ordinal)
    if kind == "table":
        _, raw_text, header_line, separator_line, row_lines, column_count = block
        return WikiTableBlock(
            raw_text=raw_text,
            header_line=header_line,
            separator_line=separator_line,
            row_lines=row_lines,
            column_count=column_count,
            source_ordinal=source_ordinal,
        )
    if kind == "code":
        _, raw_text, fence_marker, info_string, body_lines = block
        return WikiCodeBlock(
            raw_text=raw_text,
            fence_marker=fence_marker,
            info_string=info_string,
            body_lines=body_lines,
            source_ordinal=source_ordinal,
        )
    raise WikiStructureParseError(CATEGORY_STRUCTURAL_PARSE_FAILED)  # pragma: no cover
