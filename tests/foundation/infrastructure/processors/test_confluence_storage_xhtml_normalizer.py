from __future__ import annotations

import pytest

from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import WikiTableBlock
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import WikiStructureParser
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceStorageNormalizationError,
)


def _normalize(storage: str):
    return ConfluenceStorageXhtmlNormalizer().normalize(storage_xhtml=storage)


def test_inline_code_newlines_replaced_with_spaces() -> None:
    result = _normalize('<p><code>line1\nline2\r\nline3\rline4</code></p>')
    assert result.normalized_body_text == '```line1 line2 line3 line4```'
    assert '\n' not in result.normalized_body_text


def test_inline_code_with_newlines_and_backticks_gets_safe_fence() -> None:
    # Regression for the processing_failed bug found during M8-AC first
    # acceptance attempt: raw newlines inside an inline <code> span used to
    # survive normalization, so a line consisting solely of the opening
    # backtick fence could appear on its own line and be misread by
    # WikiStructureParser as an unclosed block fence. Collapsing embedded
    # newlines to spaces keeps the whole span on one line, which can never
    # match the fence-open pattern.
    result = _normalize('<p><code>line1\n`line2`\nline3</code></p>')
    assert result.normalized_body_text == '```line1 `line2` line3```'
    assert '\n' not in result.normalized_body_text
    parsed = WikiStructureParser.parse(page_title='Test', normalized_body_text=result.normalized_body_text)
    assert len(parsed.sections) > 0


def test_normalizes_baseline_blocks_inline_markup_and_unicode() -> None:
    result = _normalize(
        "<h1>Head</h1><p>Cafe\u0301 <strong>bold</strong> <em>em</em><br/>next</p>"
        "<hr/><blockquote><p>quote</p></blockquote>"
    )
    assert result.normalized_body_text == (
        "# Head\n\nCafé **bold** *em*\nnext\n\n---\n\n> quote"
    )
    assert result.warnings == ()


def test_normalization_uses_lf_trims_lines_and_collapses_blank_runs() -> None:
    result = _normalize("<p> alpha   \r\n\r\n\r\n\r\nbeta\t </p>")
    assert result.normalized_body_text == "alpha\n\nbeta"
    assert "\r" not in result.normalized_body_text


def test_does_not_prepend_page_title() -> None:
    assert _normalize("<p>body only</p>").normalized_body_text == "body only"


def test_confluence_layout_containers_preserve_block_order_without_warnings() -> None:
    result = _normalize(
        '<ac:layout>'
        '<ac:layout-section>'
        '<ac:layout-cell><h2>Left</h2><p>alpha</p></ac:layout-cell>'
        '<ac:layout-cell><p>beta</p></ac:layout-cell>'
        '</ac:layout-section>'
        '</ac:layout>'
    )
    assert result.normalized_body_text == "## Left\n\nalpha\n\nbeta"
    assert result.counters["unsupported_elements"] == 0
    assert result.warnings == ()


def test_nested_layout_preserves_lists_code_and_table_source_order() -> None:
    result = _normalize(
        '<ac:layout><ac:layout-section><ac:layout-cell>'
        '<p>intro</p><ul><li>one</li><li>two</li></ul>'
        '<ac:structured-macro ac:name="code">'
        '<ac:plain-text-body>line1\nline2</ac:plain-text-body>'
        '</ac:structured-macro>'
        '<table><tr><th>A</th></tr><tr><td>B</td></tr></table>'
        '</ac:layout-cell></ac:layout-section></ac:layout>'
    )
    text = result.normalized_body_text
    assert text.index("intro") < text.index("- one")
    assert text.index("- two") < text.index("line1")
    assert text.index("line2") < text.index("| A |")
    assert "| B |" in text
    assert result.counters["unsupported_elements"] == 0
    assert result.warnings == ()


def test_empty_layout_cells_do_not_create_content_or_unsupported_warnings() -> None:
    result = _normalize(
        '<ac:layout><ac:layout-section>'
        '<ac:layout-cell></ac:layout-cell>'
        '<ac:layout-cell><p>visible</p></ac:layout-cell>'
        '</ac:layout-section></ac:layout>'
    )
    assert result.normalized_body_text == "visible"
    assert result.counters["unsupported_elements"] == 0
    assert result.warnings == ()


def test_renders_lists_and_nested_lists_deterministically() -> None:
    result = _normalize(
        "<ol><li>one<ul><li>nested</li></ul></li><li>two</li></ol>"
    )
    assert result.normalized_body_text == "1. one\n  - nested\n2. two"


def test_renders_simple_rectangular_table_as_markdown() -> None:
    result = _normalize(
        "<table><tbody><tr><th>A</th><th>B</th></tr>"
        "<tr><td>1</td><td>x|y</td></tr></tbody></table>"
    )
    assert result.normalized_body_text == (
        "| A | B |\n| --- | --- |\n| 1 | x\\|y |"
    )
    assert result.counters["complex_tables"] == 0


def test_complex_rowspan_grid_preserves_anchor_and_covered_slot() -> None:
    result = _normalize(
        "<table><tr><td rowspan='2'>A</td><td>B</td></tr>"
        "<tr><td>C</td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| A [rowspan:2] | B |\n| --- | --- |\n|  | C |"
    )
    assert result.counters["complex_tables"] == 1
    assert result.warnings == (
        {"code": "complex_table_grid", "name": "table", "ordinal": 1},
    )


def test_irregular_rows_are_padded_without_dropping_cells() -> None:
    result = _normalize(
        "<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| A |  |\n| --- | --- |\n| B | C |"
    )
    assert result.counters["complex_tables"] == 1
    assert result.warnings[0]["code"] == "complex_table_grid"


def test_nested_table_is_rendered_inside_cell_with_stable_encoding() -> None:
    result = _normalize(
        "<table><tr><td>A<table><tr><td>nested</td></tr></table></td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| A<br><br>\\| nested \\|<br>\\| --- \\| |\n| --- |"
    )
    assert result.counters["complex_tables"] == 1
    assert result.warnings == (
        {"code": "complex_table_grid", "name": "table", "ordinal": 1},
    )


def test_invalid_span_uses_row_preserving_fallback_with_empty_cells() -> None:
    result = _normalize(
        "<table><tr><td rowspan='0'>A</td><td></td></tr>"
        "<tr><td>B</td><td></td></tr></table>"
    )
    assert result.normalized_body_text == (
        "[table]\nrow[0]: A ||\nrow[1]: B ||"
    )
    assert result.counters["complex_tables"] == 1
    assert result.warnings == (
        {"code": "complex_table_fallback", "name": "table", "ordinal": 1},
    )


def test_colspan_marker_order_and_exact_grid_width_are_stable() -> None:
    result = _normalize(
        "<table><tr><th colspan='2' rowspan='1'>Header</th></tr>"
        "<tr><td>left</td><td>right</td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| Header [colspan:2] |  |\n| --- | --- |\n| left | right |"
    )


def test_complex_cell_encoding_preserves_unique_sentinels_and_delimiters() -> None:
    result = _normalize(
        "<table><tr><td>ROWA|PIPE\\SLASH\nROWA</td><td></td></tr>"
        "<tr><td>ROWB</td><td><pre>ROWC\nROWC</pre></td></tr></table>"
    )
    text = result.normalized_body_text
    assert text.count("ROWA") == 2
    assert text.count("ROWB") == 1
    assert text.count("ROWC") == 2
    assert "ROWA\\|PIPE" in text
    assert "SLASH<br>ROWA" in text
    assert "ROWC<br>ROWC" in text
    assert result.warnings[0]["code"] == "complex_table_grid"


@pytest.mark.parametrize(
    "span",
    ["01", "0", "-1", "999999999999999999999999999999"],
)
def test_noncanonical_or_oversized_span_fails_closed_to_fallback(span: str) -> None:
    result = _normalize(
        f"<table><tr><td rowspan='{span}'>SENTINEL</td></tr></table>"
    )
    assert result.normalized_body_text == "[table]\nrow[0]: SENTINEL"
    assert result.warnings == (
        {"code": "complex_table_fallback", "name": "table", "ordinal": 1},
    )


def test_simple_table_with_span_value_one_keeps_legacy_bytes() -> None:
    result = _normalize(
        "<table><tr><th rowspan='1'>A</th><th colspan='1'>B</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| A | B |\n| --- | --- |\n| 1 | 2 |"
    )
    assert result.counters["complex_tables"] == 0
    assert result.warnings == ()


def test_nested_table_depth_is_bounded_and_each_table_is_counted_once() -> None:
    body = "leaf"
    for _ in range(7):
        body = f"<table><tr><td>{body}</td></tr></table>"
    result = _normalize(body)
    assert result.counters["complex_tables"] == 7
    assert len(result.warnings) == 7
    assert all(
        warning["code"] in {"complex_table_grid", "complex_table_fallback"}
        for warning in result.warnings
    )


def test_nested_table_depth_propagates_through_wrappers() -> None:
    body = "leaf"
    for _ in range(7):
        body = f"<table><tr><td><p>{body}</p></td></tr></table>"
    result = _normalize(body)
    assert result.counters["complex_tables"] == 7
    assert len(result.warnings) == 7
    assert any(
        warning["code"] == "complex_table_fallback"
        for warning in result.warnings
    )


def test_failed_grid_preflight_does_not_rerender_nested_cells() -> None:
    result = _normalize(
        "<table><tr><td><table><tr><td colspan='2'>nested</td></tr>"
        "<tr><td>a</td><td>b</td></tr></table></td>"
        "<td rowspan='0'>invalid</td></tr></table>"
    )
    assert result.counters["complex_tables"] == 2
    assert result.warnings == (
        {"code": "complex_table_grid", "name": "table", "ordinal": 1},
        {"code": "complex_table_fallback", "name": "table", "ordinal": 2},
    )


def test_nested_pipe_escape_keeps_outer_grid_parseable() -> None:
    result = _normalize(
        "<table><tr><td>A<table><tr><td>nested|x</td></tr></table></td></tr></table>"
    )
    document = WikiStructureParser.parse(
        page_title="Doc",
        normalized_body_text=result.normalized_body_text,
    )
    assert isinstance(document.sections[0].blocks[0], WikiTableBlock)
    assert "nested\\|x" in result.normalized_body_text


def test_fallback_enforces_the_per_cell_safety_limit_without_disclosure() -> None:
    sentinel = "SENTINEL_CELL_LIMIT"
    oversized = sentinel + ("x" * 70_000)
    with pytest.raises(ConfluenceStorageNormalizationError) as caught:
        _normalize(
            "<table><tr><td rowspan='0'>" + oversized + "</td></tr></table>"
        )
    assert str(caught.value) == "table cell exceeds safety limit"
    assert sentinel not in str(caught.value)


def test_renders_links_and_omits_unsafe_link_target() -> None:
    safe = _normalize('<p><a href="https://fixture.invalid/a">docs</a></p>')
    unsafe = _normalize('<p><a href="javascript:alert(1)">label</a></p>')
    assert safe.normalized_body_text == "[docs](https://fixture.invalid/a)"
    assert unsafe.normalized_body_text == "label"
    assert unsafe.warnings == (
        {"code": "link_target_omitted", "name": "a", "ordinal": 1},
    )


def test_malformed_link_target_is_omitted_instead_of_escaping_taxonomy() -> None:
    result = _normalize('<p><a href="http://[">label</a></p>')
    assert result.normalized_body_text == "label"
    assert result.warnings[0]["code"] == "link_target_omitted"


def test_inline_and_block_code_choose_safe_backtick_fences() -> None:
    result = _normalize("<p><code>a`b</code></p><pre>line```value</pre>")
    assert "``a`b``" in result.normalized_body_text
    assert "````\nline```value\n````" in result.normalized_body_text


def test_code_macro_preserves_code_language_title_and_safe_fence() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        '<ac:parameter ac:name="title">Example</ac:parameter>'
        '<ac:plain-text-body><![CDATA[print("```")]]></ac:plain-text-body>'
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == (
        '**Example**\n\n````python\nprint("```")\n````'
    )
    assert result.counters["handled_macros"] == {"code": 1}


def test_code_cdata_preserves_literal_declaration_and_entity_text() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="code">'
        "<ac:plain-text-body><![CDATA[<!DOCTYPE html> &unknown;]]>"
        "</ac:plain-text-body></ac:structured-macro>"
    )
    assert result.normalized_body_text == (
        "```\n<!DOCTYPE html> &unknown;\n```"
    )


def test_declaration_text_inside_xml_comment_is_not_treated_as_active() -> None:
    result = _normalize("<!-- <!ENTITY harmless 'literal'> --><p>body</p>")
    assert result.normalized_body_text == "body"


def test_unsafe_code_language_is_omitted_with_sanitized_warning() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">bad language SECRET</ac:parameter>'
        "<ac:plain-text-body>x</ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == "```\nx\n```"
    assert "SECRET" not in str(result.warnings)
    assert result.warnings[0]["code"] == "macro_parameter_omitted"


def test_expand_excerpt_and_admonition_preserve_bodies() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="title">More</ac:parameter>'
        "<ac:rich-text-body><p>expanded</p></ac:rich-text-body>"
        "</ac:structured-macro>"
        '<ac:structured-macro ac:name="excerpt">'
        "<ac:rich-text-body><p>excerpted</p></ac:rich-text-body>"
        "</ac:structured-macro>"
        '<ac:structured-macro ac:name="note">'
        "<ac:rich-text-body><p>careful</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    assert "**More**\n\nexpanded" in result.normalized_body_text
    assert "excerpted" in result.normalized_body_text
    assert "> **Note:**\n> careful" in result.normalized_body_text


@pytest.mark.parametrize("name", ["include", "excerpt-include"])
def test_include_macros_use_unknown_placeholder_when_identity_absent(name: str) -> None:
    result = _normalize(
        f'<ac:structured-macro ac:name="{name}"><ac:parameter ac:name="">SECRET</ac:parameter>'
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == "[included from page: unknown]"


def test_include_macro_preserves_observed_page_title_or_id() -> None:
    titled = _normalize(
        '<ac:structured-macro ac:name="include">'
        '<ri:page ri:content-title="Target Page" ri:content-id="2000"/>'
        "</ac:structured-macro>"
    )
    identified = _normalize(
        '<ac:structured-macro ac:name="excerpt-include">'
        '<ri:page ri:content-id="2000"/>'
        "</ac:structured-macro>"
    )
    assert titled.normalized_body_text == "[included from page: Target Page]"
    assert identified.normalized_body_text == "[included from page: 2000]"


def test_reference_intents_preserve_mixed_source_order_and_status() -> None:
    result = _normalize(
        '<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>'
        '<ac:structured-macro ac:name="include">'
        '<ri:page ri:content-title="Design"/></ac:structured-macro>'
        '<ac:structured-macro ac:name="drawio">'
        '<ac:parameter ac:name="diagramName">flow</ac:parameter>'
        '</ac:structured-macro>'
    )
    assert result.reference_intents == (
        NormalizationReferenceIntent(
            ordinal=1,
            kind="image_attachment",
            status="deferred_mvp",
            target_identity="diagram.png",
            placeholder_identity="diagram.png",
        ),
        NormalizationReferenceIntent(
            ordinal=2,
            kind="include_page",
            status="unresolved_target",
            target_identity="Design",
            placeholder_identity="Design",
        ),
        NormalizationReferenceIntent(
            ordinal=3,
            kind="drawio",
            status="deferred_mvp",
            target_identity="flow",
            placeholder_identity="flow",
        ),
    )


def test_missing_reference_identity_is_unresolved_and_leak_safe() -> None:
    result = _normalize(
        '<ac:image alt="SECRET\nvalue"/>'
        '<ac:structured-macro ac:name="drawio"/>'
        '<ac:structured-macro ac:name="include">'
        '<ac:parameter ac:name="page">SECRET</ac:parameter>'
        '</ac:structured-macro>'
    )
    assert result.reference_intents[0].target_identity == "SECRET value"
    assert result.reference_intents[0].status == "deferred_mvp"
    assert result.reference_intents[1].target_identity == "unknown"
    assert result.reference_intents[1].status == "unresolved_target"
    assert result.reference_intents[2].status == "unresolved_target"
    assert "SECRET" not in str(result.warnings)


def test_reference_identity_is_bounded_and_control_safe() -> None:
    value = "x" * 300
    result = _normalize(f'<ac:image alt="{value}"/>')
    assert result.normalized_body_text == "[media: unknown]"
    assert result.reference_intents[0].target_identity == "unknown"

    escaped_overflow = _normalize(f'<ac:image alt="{"[" * 130}"/>')
    assert escaped_overflow.reference_intents[0].target_identity == "unknown"


@pytest.mark.parametrize("name", ["drawio", "drawio-sketch", "drawio-board"])
def test_drawio_macros_emit_media_placeholder(name: str) -> None:
    result = _normalize(f'<ac:structured-macro ac:name="{name}"/>')
    assert result.normalized_body_text == "[diagram: unknown]"
    assert result.counters["media_placeholders"] == 1


def test_drawio_macro_preserves_observed_diagram_name() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="drawio">'
        '<ac:parameter ac:name="diagramName">flow-v2</ac:parameter>'
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == "[diagram: flow-v2]"


def test_jira_macro_emits_only_valid_issue_key() -> None:
    valid = _normalize(
        '<ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="key">ABC-123</ac:parameter>'
        "</ac:structured-macro>"
    )
    invalid = _normalize(
        '<ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="key">SECRET value</ac:parameter>'
        "</ac:structured-macro>"
    )
    assert valid.normalized_body_text == "ABC-123"
    assert invalid.normalized_body_text == "[jira-issue]"
    assert "SECRET" not in str(invalid.warnings)


def test_toc_is_dropped_and_counted() -> None:
    result = _normalize('<p>before</p><ac:structured-macro ac:name="toc"/><p>after</p>')
    assert result.normalized_body_text == "before\n\nafter"
    assert result.counters["toc_dropped"] == 1


def test_confluence_image_and_attachment_link_use_generic_placeholders() -> None:
    result = _normalize(
        '<ac:image><ri:attachment ri:filename="SECRET.png"/></ac:image>'
        '<ac:link><ri:attachment ri:filename="OTHER.pdf"/></ac:link>'
    )
    assert result.normalized_body_text == (
        "[media: SECRET.png][media: OTHER.pdf]"
    )
    assert result.counters["media_placeholders"] == 2
    assert "SECRET" not in str(result.warnings)


def test_placeholder_identity_is_markdown_safe_without_losing_text() -> None:
    result = _normalize(
        '<ac:image><ri:attachment ri:filename="arch[final].png"/></ac:image>'
    )
    assert result.normalized_body_text == "[media: arch\\[final\\].png]"


def test_unknown_macro_preserves_rich_body_and_warns_in_source_order() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="widget">'
        "<ac:rich-text-body><p>meaningful</p></ac:rich-text-body>"
        "</ac:structured-macro>"
        '<ac:structured-macro ac:name="empty"/>'
    )
    assert result.normalized_body_text == (
        "[macro:widget]\n\nmeaningful\n\n[macro:empty omitted]"
    )
    assert result.counters["unhandled_macros"] == {"empty": 1, "widget": 1}
    assert result.warnings == (
        {"code": "unhandled_macro", "name": "widget", "ordinal": 1},
        {"code": "unhandled_macro", "name": "empty", "ordinal": 2},
    )


def test_unknown_macro_preserves_plain_text_body_lines() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="noformat">'
        "<ac:plain-text-body>raw log line 1\nraw log line 2</ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == (
        "[macro:noformat]\n\nraw log line 1\nraw log line 2"
    )
    assert result.counters["unhandled_macros"] == {"noformat": 1}


def test_unsafe_unknown_macro_name_is_not_disclosed() -> None:
    result = _normalize(
        '<ac:structured-macro ac:name="SECRET / private"><ac:rich-text-body><p>x</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert result.normalized_body_text.startswith("[macro:unknown]")
    assert result.warnings[0]["name"] == "unknown"
    assert "SECRET" not in str(result.warnings)


def test_unknown_element_preserves_text_and_adds_sanitized_warning() -> None:
    result = _normalize("<custom-element>meaningful</custom-element>")
    assert result.normalized_body_text == "meaningful"
    assert result.counters["unsupported_elements"] == 1
    assert result.warnings == (
        {"code": "unsupported_element", "name": "custom-element", "ordinal": 1},
    )


def test_script_content_is_not_rendered() -> None:
    result = _normalize("<script>REVIEW_SENTINEL_SECRET</script>")
    assert result.normalized_body_text == "[unsupported:script omitted]"
    assert "REVIEW_SENTINEL_SECRET" not in str(result.warnings)


def test_safe_html_named_entity_is_supported_without_entity_resolution() -> None:
    assert _normalize("<p>a&nbsp;b</p>").normalized_body_text == "a b"


@pytest.mark.parametrize(
    "storage",
    [
        '<!DOCTYPE page [<!ENTITY xxe SYSTEM "file:///secret">]><p>&xxe;</p>',
        '<!ENTITY xxe "secret"><p>&xxe;</p>',
    ],
)
def test_doctype_and_entity_declarations_fail_closed(storage: str) -> None:
    with pytest.raises(
        ConfluenceStorageNormalizationError,
        match="forbidden declaration",
    ):
        _normalize(storage)


def test_unknown_entity_fails_closed_without_disclosure() -> None:
    with pytest.raises(ConfluenceStorageNormalizationError) as caught:
        _normalize("<p>&REVIEW_SENTINEL_SECRET;</p>")
    assert "REVIEW_SENTINEL_SECRET" not in str(caught.value)


@pytest.mark.parametrize("storage", ["<p>", "<p><b>x</p>", "\x00"])
def test_malformed_xhtml_fails_closed_without_raw_content(storage: str) -> None:
    with pytest.raises(ConfluenceStorageNormalizationError) as caught:
        _normalize(storage)
    assert storage not in str(caught.value)


def test_unbound_namespace_prefix_fails_closed() -> None:
    with pytest.raises(ConfluenceStorageNormalizationError, match="malformed"):
        _normalize("<at:var>value</at:var>")


def test_preformatted_code_inside_list_keeps_fence_and_line_structure() -> None:
    result = _normalize("<ul><li>intro<pre>line1\nline2\nline3</pre></li></ul>")
    assert result.normalized_body_text == (
        "- intro\n\n  ```\n  line1\n  line2\n  line3\n  ```"
    )
    assert "line1 line2" not in result.normalized_body_text


def test_code_macro_inside_list_keeps_indentation() -> None:
    result = _normalize(
        '<ul><li>code<ac:structured-macro ac:name="code">'
        '<ac:plain-text-body>def f():\n    return 1</ac:plain-text-body>'
        "</ac:structured-macro></li></ul>"
    )
    assert "  def f():\n      return 1" in result.normalized_body_text
    assert "def f(): return 1" not in result.normalized_body_text


def test_code_inside_table_uses_complex_grid_without_flattening() -> None:
    result = _normalize(
        "<table><tr><th>Code</th></tr><tr><td><pre>line1\nline2</pre></td></tr></table>"
    )
    assert result.normalized_body_text == (
        "| Code |\n| --- |\n| ```<br>line1<br>line2<br>``` |"
    )
    assert result.counters["complex_tables"] == 1
    assert result.warnings[-1]["code"] == "complex_table_grid"


def test_result_repr_does_not_disclose_normalized_body() -> None:
    result = _normalize("<p>REVIEW_SENTINEL_SECRET</p>")
    assert "REVIEW_SENTINEL_SECRET" not in repr(result)
