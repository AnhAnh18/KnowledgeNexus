from __future__ import annotations

import ast
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiCodeBlock,
    WikiDocumentStructure,
    WikiProseBlock,
    WikiSection,
    WikiTableBlock,
)
from knowledgenexus.foundation.domain.rules import wiki_structure_parser as parser_module
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    CATEGORY_EMPTY_STRUCTURAL_HEADING,
    CATEGORY_INVALID_NORMALIZED_TEXT,
    CATEGORY_INVALID_PAGE_TITLE,
    CATEGORY_NON_CANONICAL_NORMALIZED_TEXT,
    CATEGORY_UNCLOSED_CODE_FENCE,
    WikiStructureParseError,
    WikiStructureParser,
)


def parse(title: str, body: str) -> WikiDocumentStructure:
    return WikiStructureParser.parse(page_title=title, normalized_body_text=body)


def all_blocks(document: WikiDocumentStructure) -> list[object]:
    blocks: list[object] = []
    for section in document.sections:
        blocks.extend(section.blocks)
    return blocks


def block(document: WikiDocumentStructure, section_index: int, block_index: int) -> object:
    return document.sections[section_index].blocks[block_index]


# ---------------------------------------------------------------------------
# Preamble / documents starting with headings
# ---------------------------------------------------------------------------


def test_preamble_before_first_heading_uses_page_title_and_none_metadata() -> None:
    document = parse("Page", "Intro line.\n\n## Section\n\nBody.")
    preamble = document.sections[0]
    assert preamble.heading_path == ("Page",)
    assert preamble.heading_level is None
    assert preamble.heading_source_line is None
    assert isinstance(preamble.blocks[0], WikiProseBlock)
    assert preamble.blocks[0].text == "Intro line."


def test_document_starting_with_heading_has_no_empty_preamble() -> None:
    document = parse("Page", "# Top\n\nbody")
    assert document.sections[0].heading_level == 1
    assert all(section.heading_path != ("Page",) for section in document.sections)


def test_empty_body_returns_zero_sections() -> None:
    document = parse("Page", "")
    assert document.page_title == "Page"
    assert document.sections == ()


def test_body_with_only_whitespace_is_non_canonical() -> None:
    # A blank-only body is not canonical M6C output (leading/trailing blanks are
    # stripped), so it fails closed rather than becoming an empty preamble.
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Page", "\n")
    assert excinfo.value.category == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


# ---------------------------------------------------------------------------
# h1-h3 stack behaviour, skipped and duplicate levels
# ---------------------------------------------------------------------------


def test_heading_stack_builds_nested_paths() -> None:
    document = parse("Doc", "# A\n\ntext a\n\n## B\n\ntext b\n\n### C\n\ntext c")
    paths = [section.heading_path for section in document.sections]
    assert paths == [
        ("Doc", "A"),
        ("Doc", "A", "B"),
        ("Doc", "A", "B", "C"),
    ]


def test_heading_stack_pops_same_and_deeper_levels() -> None:
    document = parse("Doc", "# A\n\n## B\n\n### C\n\n## D")
    paths = [section.heading_path for section in document.sections]
    assert paths == [
        ("Doc", "A"),
        ("Doc", "A", "B"),
        ("Doc", "A", "B", "C"),
        ("Doc", "A", "D"),
    ]


def test_skipped_heading_level_does_not_invent_missing_levels() -> None:
    document = parse("Doc", "# A\n\n### C")
    assert document.sections[1].heading_path == ("Doc", "A", "C")
    assert document.sections[1].heading_level == 3


def test_duplicate_heading_names_are_preserved() -> None:
    document = parse("Doc", "## B\n\n## B")
    assert [section.heading_path for section in document.sections] == [
        ("Doc", "B"),
        ("Doc", "B"),
    ]


def test_sibling_after_deeper_heading_resets_to_parent() -> None:
    document = parse("Doc", "## A\n\n#### deep stays prose\n\n## Bee")
    # h4 is prose inside section A; Bee is a sibling h2.
    assert document.sections[0].heading_path == ("Doc", "A")
    assert isinstance(document.sections[0].blocks[0], WikiProseBlock)
    assert document.sections[1].heading_path == ("Doc", "Bee")


# ---------------------------------------------------------------------------
# h4-h6 remain prose
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", ["####", "#####", "######"])
def test_h4_to_h6_headings_remain_prose(marker: str) -> None:
    document = parse("Doc", f"{marker} Heading text")
    assert len(document.sections) == 1
    assert document.sections[0].heading_level is None
    prose = document.sections[0].blocks[0]
    assert isinstance(prose, WikiProseBlock)
    assert prose.text == f"{marker} Heading text"


def test_seven_hashes_and_no_space_are_prose() -> None:
    document = parse("Doc", "####### seven\n\n#nospace")
    prose_texts = [b.text for b in all_blocks(document) if isinstance(b, WikiProseBlock)]
    assert prose_texts == ["####### seven\n\n#nospace"]
    assert document.sections[0].heading_level is None


# ---------------------------------------------------------------------------
# Empty headed sections preserved; empty structural heading fails closed
# ---------------------------------------------------------------------------


def test_empty_headed_sections_are_preserved() -> None:
    document = parse("Doc", "## Empty\n\n## Full\n\nbody")
    assert document.sections[0].heading_path == ("Doc", "Empty")
    assert document.sections[0].blocks == ()
    assert document.sections[1].heading_path == ("Doc", "Full")
    assert len(document.sections[1].blocks) == 1


@pytest.mark.parametrize("heading", ["#", "##", "###"])
def test_empty_structural_heading_fails_closed(heading: str) -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", heading)
    assert excinfo.value.category == CATEGORY_EMPTY_STRUCTURAL_HEADING


# ---------------------------------------------------------------------------
# Headings inside code / list / blockquote / indented remain non-structural
# ---------------------------------------------------------------------------


def test_heading_inside_code_fence_stays_code_body() -> None:
    document = parse("Doc", "```\n# not a heading\n## also not\n```")
    assert len(document.sections) == 1
    code = document.sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.body_lines == ("# not a heading", "## also not")


@pytest.mark.parametrize(
    "line",
    ["- # list item hash", "> # quoted hash", "  # indented hash", "1. # ordered hash"],
)
def test_heading_like_text_in_list_quote_or_indent_is_prose(line: str) -> None:
    document = parse("Doc", line)
    assert document.sections[0].heading_level is None
    assert isinstance(document.sections[0].blocks[0], WikiProseBlock)
    assert document.sections[0].blocks[0].text == line


# ---------------------------------------------------------------------------
# Code fences: variable length, shorter inner runs, info strings, blank lines
# ---------------------------------------------------------------------------


def test_variable_length_fence_preserves_shorter_inner_fences() -> None:
    body = "````text\n```\ninner still code\n```\n````"
    code = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.fence_marker == "````"
    assert code.info_string == "text"
    assert code.body_lines == ("```", "inner still code", "```")
    assert code.raw_text == body


def test_closing_fence_may_be_longer_than_opening() -> None:
    body = "```\nbody\n`````"
    code = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.body_lines == ("body",)


def test_code_info_string_and_blank_body_line_preserved() -> None:
    body = "```python\nfirst\n\nthird\n```"
    code = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.info_string == "python"
    assert code.body_lines == ("first", "", "third")


def test_empty_info_string_when_no_language() -> None:
    code = parse("Doc", "```\nplain\n```").sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.info_string == ""


def test_table_and_heading_lines_in_code_body_stay_code() -> None:
    body = "```\n| a | b |\n| --- | --- |\n### heading\n```"
    code = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(code, WikiCodeBlock)
    assert code.body_lines == ("| a | b |", "| --- | --- |", "### heading")


def test_unclosed_code_fence_fails_closed() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", "```python\nno close here")
    assert excinfo.value.category == CATEGORY_UNCLOSED_CODE_FENCE


# ---------------------------------------------------------------------------
# Indented fenced code (M6C emits these inside list items)
# ---------------------------------------------------------------------------


def test_indented_fence_inside_list_is_a_code_block() -> None:
    body = "- intro\n\n  ```\n  | a | b |\n  | --- | --- |\n  ```"
    document = parse("Doc", body)
    kinds = [type(b).__name__ for b in all_blocks(document)]
    # The table-shaped fence body must not leak as a table.
    assert kinds == ["WikiProseBlock", "WikiCodeBlock"]
    code = all_blocks(document)[1]
    assert isinstance(code, WikiCodeBlock)
    assert code.body_lines == ("  | a | b |", "  | --- | --- |")
    assert code.raw_text == "  ```\n  | a | b |\n  | --- | --- |\n  ```"


def test_indented_unclosed_fence_fails_closed() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", "- item\n\n  ```\n  code with no close")
    assert excinfo.value.category == CATEGORY_UNCLOSED_CODE_FENCE


def test_indented_table_like_lines_stay_prose() -> None:
    # A pipe/dash table indented inside a list is part of the list (prose).
    body = "- with table\n\n  | H |\n  | --- |\n  | V |"
    document = parse("Doc", body)
    assert all(not isinstance(b, WikiTableBlock) for b in all_blocks(document))


def test_m6c_generated_indented_fence_is_retained_as_code() -> None:
    # Regression guard for the P1.1 defect using real M6C normalizer output
    # rather than a hand-written fixture: a code macro inside a list produces an
    # indented fence whose table-shaped body must stay inside the code block.
    from knowledgenexus.foundation.infrastructure.processors.confluence_storage_xhtml_normalizer import (  # noqa: E501
        ConfluenceStorageXhtmlNormalizer,
    )

    xhtml = (
        "<ul><li>intro"
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        "| a | b |\n| --- | --- |"
        "</ac:plain-text-body></ac:structured-macro></li></ul>"
    )
    body = (
        ConfluenceStorageXhtmlNormalizer()
        .normalize(storage_xhtml=xhtml)
        .normalized_body_text
    )
    document = parse("Doc", body)
    kinds = [type(b).__name__ for b in all_blocks(document)]
    assert "WikiCodeBlock" in kinds
    assert all(kind != "WikiTableBlock" for kind in kinds)


# ---------------------------------------------------------------------------
# Tables: simple, aligned, escaped pipes, header-only
# ---------------------------------------------------------------------------


def test_simple_table_recognized() -> None:
    body = "| Name | Value |\n| --- | --- |\n| a | 1 |\n| b | 2 |"
    table = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(table, WikiTableBlock)
    assert table.header_line == "| Name | Value |"
    assert table.separator_line == "| --- | --- |"
    assert table.row_lines == ("| a | 1 |", "| b | 2 |")
    assert table.column_count == 2
    assert table.raw_text == body


@pytest.mark.parametrize(
    "separator", ["| --- | --- | --- |", "| ---- | ----- | --- |"]
)
def test_hyphen_run_separators_recognized(separator: str) -> None:
    # M6C emits separator cells as runs of three or more hyphens (no colons).
    body = f"| a | b | c |\n{separator}\n| 1 | 2 | 3 |"
    table = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(table, WikiTableBlock)
    assert table.column_count == 3


@pytest.mark.parametrize(
    "separator",
    ["| - | - |", "| -- | -- |", "| :--- | ---: |", "| :-: | :-: |"],
)
def test_short_or_colon_separators_are_not_tables(separator: str) -> None:
    # A single/double hyphen or an alignment-colon cell is not M6C separator
    # syntax, so the whole block stays prose (malformed table-like text).
    document = parse("Doc", f"| a | b |\n{separator}\n| 1 | 2 |")
    assert all(not isinstance(b, WikiTableBlock) for b in all_blocks(document))


def test_escaped_pipe_does_not_add_columns() -> None:
    body = "| left | right |\n| --- | --- |\n| a \\| b | c |"
    table = parse("Doc", body).sections[0].blocks[0]
    assert isinstance(table, WikiTableBlock)
    assert table.column_count == 2
    assert table.row_lines == ("| a \\| b | c |",)


def test_header_only_table_without_body_rows() -> None:
    table = parse("Doc", "| h1 | h2 |\n| --- | --- |").sections[0].blocks[0]
    assert isinstance(table, WikiTableBlock)
    assert table.row_lines == ()
    assert table.column_count == 2


# ---------------------------------------------------------------------------
# Non-table pipe prose and malformed / non-rectangular tables stay prose
# ---------------------------------------------------------------------------


def test_pipe_prose_without_separator_is_prose() -> None:
    document = parse("Doc", "a | b | c")
    assert isinstance(document.sections[0].blocks[0], WikiProseBlock)
    assert document.sections[0].blocks[0].text == "a | b | c"


def test_pipe_line_followed_by_thematic_break_is_not_a_table() -> None:
    # A header line has a pipe but the following line has no pipe, so it is not a
    # separator: no false-positive single-column table.
    document = parse("Doc", "Summary | detail\n\n---")
    assert all(not isinstance(b, WikiTableBlock) for b in all_blocks(document))


def test_complex_table_fallback_marker_stays_prose() -> None:
    # This is exactly what the M6C normalizer emits for complex tables.
    body = "[table]\nA | B\nC | D"
    document = parse("Doc", body)
    assert len(all_blocks(document)) == 1
    prose = document.sections[0].blocks[0]
    assert isinstance(prose, WikiProseBlock)
    assert prose.text == body


def test_non_rectangular_table_like_block_stays_prose_entirely() -> None:
    body = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| only-one |"
    document = parse("Doc", body)
    assert all(not isinstance(b, WikiTableBlock) for b in all_blocks(document))
    # Nothing is dropped or repaired: the whole block is retained verbatim.
    assert all_blocks(document)[0].text == body


def test_header_separator_column_mismatch_is_prose() -> None:
    body = "| a | b | c |\n| --- | --- |"
    document = parse("Doc", body)
    assert all(not isinstance(b, WikiTableBlock) for b in all_blocks(document))


# ---------------------------------------------------------------------------
# Prose: paragraphs, lists, blockquotes, rules, placeholders, links
# ---------------------------------------------------------------------------


def test_prose_preserves_internal_blank_lines_as_one_block() -> None:
    body = "Para one.\n\nPara two.\n\nPara three."
    document = parse("Doc", body)
    assert len(all_blocks(document)) == 1
    assert all_blocks(document)[0].text == body


def test_placeholders_lists_blockquotes_and_rules_are_prose() -> None:
    body = (
        "- item\n- item two\n\n"
        "> quote line\n\n"
        "---\n\n"
        "[media: diagram.png]\n\n"
        "[included from page: Design]\n\n"
        "[jira-issue]"
    )
    document = parse("Doc", body)
    assert len(all_blocks(document)) == 1
    prose = all_blocks(document)[0]
    assert isinstance(prose, WikiProseBlock)
    assert prose.text == body


# ---------------------------------------------------------------------------
# Adjacency without content loss
# ---------------------------------------------------------------------------


def test_adjacent_blocks_are_all_captured_without_loss() -> None:
    body = (
        "lead prose\n\n"
        "```\ncode body\n```\n\n"
        "| h |\n| --- |\n| v |\n\n"
        "tail prose"
    )
    document = parse("Doc", body)
    kinds = [type(b).__name__ for b in all_blocks(document)]
    assert kinds == [
        "WikiProseBlock",
        "WikiCodeBlock",
        "WikiTableBlock",
        "WikiProseBlock",
    ]


def test_heading_immediately_after_block_without_blank_line() -> None:
    # The scanner does not depend on blank separators to close a code block.
    document = parse("Doc", "```\nx\n```\n## After")
    assert isinstance(block(document, 0, 0), WikiCodeBlock)
    assert document.sections[1].heading_path == ("Doc", "After")


# ---------------------------------------------------------------------------
# Repeated content, source ordinals, coverage, determinism
# ---------------------------------------------------------------------------


def test_repeated_content_is_not_deduplicated() -> None:
    body = "same line\n\nsame line\n\nsame line"
    document = parse("Doc", body)
    assert all_blocks(document)[0].text == body


def test_source_ordinals_form_deterministic_total_order() -> None:
    body = "pre\n\n# A\n\nbody a\n\n## B\n\nbody b"
    document = parse("Doc", body)
    ordinals: list[int] = []
    for section in document.sections:
        ordinals.append(section.source_ordinal)
        ordinals.extend(b.source_ordinal for b in section.blocks)
    assert ordinals == sorted(ordinals)
    assert ordinals == list(range(len(ordinals)))
    assert len(set(ordinals)) == len(ordinals)


def test_semantic_coverage_preserves_every_content_line() -> None:
    body = (
        "intro\n\n"
        "## Overview\n\n"
        "para\n\n"
        "| h | k |\n| --- | --- |\n| 1 | 2 |\n\n"
        "### Code\n\n"
        "```py\nline1\nline2\n```\n\n"
        "#### h4 prose"
    )
    document = parse("Doc", body)
    reconstructed: list[str] = []
    for section in sorted(
        (s for s in document.sections), key=lambda s: s.source_ordinal
    ):
        if section.heading_level is not None:
            marker = "#" * section.heading_level
            reconstructed.append(f"{marker} {section.heading_path[-1]}")
        for wiki_block in sorted(section.blocks, key=lambda b: b.source_ordinal):
            raw = getattr(wiki_block, "raw_text", None)
            if raw is None:
                raw = wiki_block.text
            reconstructed.extend(raw.split("\n"))
    original_lines = [line for line in body.split("\n") if line != ""]
    reconstructed_lines = [line for line in reconstructed if line != ""]
    # Ordered (not sorted) equality forces source-order preservation, not just
    # membership: every content line reappears exactly once, in source order.
    assert reconstructed_lines == original_lines


def test_same_input_returns_exactly_equal_structure() -> None:
    body = "pre\n\n# A\n\n```\ncode\n```\n\n| h |\n| --- |\n| v |"
    first = parse("Doc", body)
    second = parse("Doc", body)
    assert first == second
    assert hash(first) == hash(second)


def test_input_string_is_not_mutated() -> None:
    body = "intro\n\n## S\n\nbody"
    snapshot = str(body)
    parse("Doc", body)
    assert body == snapshot


# ---------------------------------------------------------------------------
# NFC / LF preconditions and sanitized failures
# ---------------------------------------------------------------------------


def test_crlf_line_endings_are_non_canonical() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", "a\r\nb")
    assert excinfo.value.category == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


def test_trailing_whitespace_is_non_canonical() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", "line with trailing space ")
    assert excinfo.value.category == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


def test_non_nfc_text_is_non_canonical() -> None:
    decomposed = "Café"  # 'e' + combining acute; NFC would compose it
    assert decomposed != "".join(("Caf", "é"))
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", decomposed)
    assert excinfo.value.category == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


def test_collapsible_blank_runs_are_non_canonical() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("Doc", "a\n\n\nb")
    assert excinfo.value.category == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


@pytest.mark.parametrize("bad_title", [None, "", "   ", 123, b"bytes"])
def test_invalid_page_title_fails_closed(bad_title: object) -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        WikiStructureParser.parse(page_title=bad_title, normalized_body_text="body")
    assert excinfo.value.category == CATEGORY_INVALID_PAGE_TITLE


@pytest.mark.parametrize("bad_body", [None, 123, b"bytes", ["a"]])
def test_non_string_body_fails_closed(bad_body: object) -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        WikiStructureParser.parse(page_title="Doc", normalized_body_text=bad_body)
    assert excinfo.value.category == CATEGORY_INVALID_NORMALIZED_TEXT


def test_failures_do_not_leak_content_in_message() -> None:
    secret_body = "SENSITIVE-CONTENT\r\nmore"
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse("SECRET-TITLE", secret_body)
    message = str(excinfo.value)
    assert "SENSITIVE-CONTENT" not in message
    assert "SECRET-TITLE" not in message
    assert message == CATEGORY_NON_CANONICAL_NORMALIZED_TEXT


# ---------------------------------------------------------------------------
# Zero tokenizer / network / filesystem / chunking dependencies
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_parser_module_has_no_forbidden_dependencies() -> None:
    allowed = {
        "__future__",
        "re",
        "knowledgenexus.foundation.domain.models.wiki_document_structure",
        "knowledgenexus.foundation.domain.rules.text_normalization",
    }
    imports = _imported_modules(Path(parser_module.__file__))
    assert imports <= allowed, f"unexpected imports: {sorted(imports - allowed)}"


_FORBIDDEN_DEPENDENCY_PREFIXES = (
    "os",
    "io",
    "sys",
    "pathlib",
    "socket",
    "ssl",
    "urllib",
    "http",
    "requests",
    "tokenizers",
    "transformers",
    "sentencepiece",
    "huggingface_hub",
    "FlagEmbedding",
    "torch",
    "knowledgenexus.foundation.infrastructure",
    "knowledgenexus.indexing",
)


def _assert_no_forbidden_dependencies(module_file: str) -> None:
    for name in _imported_modules(Path(module_file)):
        for prefix in _FORBIDDEN_DEPENDENCY_PREFIXES:
            assert name != prefix and not name.startswith(f"{prefix}."), (
                module_file,
                name,
            )
        # No tokenizer, tokenization, or chunking coupling of any kind.
        assert "token" not in name.lower(), (module_file, name)
        assert "chunk" not in name.lower(), (module_file, name)


def test_parser_imports_no_tokenizer_network_or_filesystem_modules() -> None:
    _assert_no_forbidden_dependencies(parser_module.__file__)


def test_every_new_production_module_has_no_forbidden_dependencies() -> None:
    from knowledgenexus.foundation.application.use_cases import (
        parse_wiki_document_structure as adapter_module,
    )
    from knowledgenexus.foundation.domain.models import (
        wiki_document_structure as models_module,
    )

    for module in (parser_module, models_module, adapter_module):
        _assert_no_forbidden_dependencies(module.__file__)
