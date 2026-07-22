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


def test_ordered_collections_are_defensively_copied_to_tuples() -> None:
    prose = WikiProseBlock(text="hello", source_ordinal=1)
    blocks = [prose]
    heading_path = ["Page"]
    section = WikiSection(
        heading_path=heading_path,  # type: ignore[arg-type]
        heading_level=None,
        heading_source_line=None,
        source_ordinal=0,
        blocks=blocks,  # type: ignore[arg-type]
    )
    sections = [section]
    document = WikiDocumentStructure(
        page_title="Page",
        sections=sections,  # type: ignore[arg-type]
    )

    heading_path.append("mutated")
    blocks.clear()
    sections.clear()

    assert section.heading_path == ("Page",)
    assert section.blocks == (prose,)
    assert document.sections == (section,)
    assert hash(document)


def test_table_and_code_line_collections_are_defensively_copied() -> None:
    rows = ["| value |"]
    body_lines = ["line"]
    table = WikiTableBlock(
        raw_text="| h |\n| --- |\n| value |",
        header_line="| h |",
        separator_line="| --- |",
        row_lines=rows,  # type: ignore[arg-type]
        column_count=1,
        source_ordinal=1,
    )
    code = WikiCodeBlock(
        raw_text="```\nline\n```",
        fence_marker="```",
        info_string="",
        body_lines=body_lines,  # type: ignore[arg-type]
        source_ordinal=2,
    )

    rows.clear()
    body_lines.clear()

    assert table.row_lines == ("| value |",)
    assert code.body_lines == ("line",)


@pytest.mark.parametrize(
    "values",
    ["scalar", b"bytes", {"unordered"}, {"key": "value"}],
)
def test_ordered_collections_reject_scalar_or_unordered_inputs(
    values: object,
) -> None:
    with pytest.raises(TypeError):
        WikiDocumentStructure(
            page_title="Page",
            sections=values,  # type: ignore[arg-type]
        )


def test_ordered_collections_reject_wrong_entry_types() -> None:
    with pytest.raises(TypeError):
        WikiSection(
            heading_path=("Page",),
            heading_level=None,
            heading_source_line=None,
            source_ordinal=0,
            blocks=(object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        WikiCodeBlock(
            raw_text="```\nline\n```",
            fence_marker="```",
            info_string="",
            body_lines=(1,),  # type: ignore[arg-type]
            source_ordinal=1,
        )


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
