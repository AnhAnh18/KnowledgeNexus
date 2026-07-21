from __future__ import annotations

import dataclasses

import pytest

from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiCodeBlock,
    WikiDocumentStructure,
    WikiProseBlock,
    WikiSection,
    WikiTableBlock,
)


def _document() -> WikiDocumentStructure:
    prose = WikiProseBlock(text="hello", source_ordinal=1)
    table = WikiTableBlock(
        raw_text="| a |\n| --- |\n| 1 |",
        header_line="| a |",
        separator_line="| --- |",
        row_lines=("| 1 |",),
        column_count=1,
        source_ordinal=2,
    )
    code = WikiCodeBlock(
        raw_text="```py\nx = 1\n```",
        fence_marker="```",
        info_string="py",
        body_lines=("x = 1",),
        source_ordinal=3,
    )
    section = WikiSection(
        heading_path=("Page", "Overview"),
        heading_level=2,
        heading_source_line=3,
        source_ordinal=0,
        blocks=(prose, table, code),
    )
    return WikiDocumentStructure(page_title="Page", sections=(section,))


def test_models_are_frozen_immutable() -> None:
    document = _document()
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.page_title = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.sections[0].blocks[0].text = "mutated"  # type: ignore[misc]


def test_equal_structures_compare_equal_and_hash_equal() -> None:
    assert _document() == _document()
    assert hash(_document()) == hash(_document())


def test_distinct_content_is_not_equal() -> None:
    other_section = dataclasses.replace(
        _document().sections[0],
        blocks=(WikiProseBlock(text="different", source_ordinal=1),),
    )
    assert WikiDocumentStructure(page_title="Page", sections=(other_section,)) != _document()


def test_repr_does_not_leak_content() -> None:
    # Content-bearing models disable repr so prose/code/table text cannot appear
    # in tracebacks or logs (sanitization requirement).
    prose = WikiProseBlock(text="secret content", source_ordinal=1)
    assert "secret content" not in repr(prose)
    document = _document()
    assert "hello" not in repr(document)
    assert "Overview" not in repr(document)


def test_fields_preserve_supplied_values() -> None:
    document = _document()
    section = document.sections[0]
    assert section.heading_path == ("Page", "Overview")
    assert section.heading_level == 2
    assert section.heading_source_line == 3
    assert isinstance(section.blocks, tuple)
    table = section.blocks[1]
    assert isinstance(table, WikiTableBlock)
    assert table.row_lines == ("| 1 |",)
    assert table.column_count == 1
    code = section.blocks[2]
    assert isinstance(code, WikiCodeBlock)
    assert code.body_lines == ("x = 1",)
    assert code.info_string == "py"


def test_preamble_section_uses_none_heading_metadata() -> None:
    section = WikiSection(
        heading_path=("Page",),
        heading_level=None,
        heading_source_line=None,
        source_ordinal=0,
        blocks=(WikiProseBlock(text="intro", source_ordinal=1),),
    )
    assert section.heading_level is None
    assert section.heading_source_line is None
    assert section.heading_path == ("Page",)
