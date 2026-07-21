from __future__ import annotations

import pytest

from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceStorageNormalizationError,
)


def _normalize(storage: str):
    return ConfluenceStorageXhtmlNormalizer().normalize(storage_xhtml=storage)


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


@pytest.mark.parametrize(
    ("storage", "expected_text"),
    [
        (
            "<table><tr><td rowspan='2'>A</td><td>B</td></tr><tr><td>C</td></tr></table>",
            "B",
        ),
        (
            "<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>",
            "B",
        ),
        (
            "<table><tr><td>A<table><tr><td>nested</td></tr></table></td></tr></table>",
            "nested",
        ),
    ],
)
def test_complex_table_falls_back_without_dropping_cell_text(
    storage: str,
    expected_text: str,
) -> None:
    result = _normalize(storage)
    assert result.normalized_body_text.startswith("[table]")
    assert "A" in result.normalized_body_text
    assert expected_text in result.normalized_body_text
    assert result.counters["complex_tables"] == 1
    assert result.warnings == (
        {"code": "complex_table_fallback", "name": "table", "ordinal": 1},
    )


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
def test_include_macros_use_identity_free_placeholder(name: str) -> None:
    result = _normalize(
        f'<ac:structured-macro ac:name="{name}"><ac:parameter ac:name="">SECRET</ac:parameter>'
        "</ac:structured-macro>"
    )
    assert result.normalized_body_text == "[included-page]"


@pytest.mark.parametrize("name", ["drawio", "drawio-sketch", "drawio-board"])
def test_drawio_macros_emit_media_placeholder(name: str) -> None:
    result = _normalize(f'<ac:structured-macro ac:name="{name}"/>')
    assert result.normalized_body_text == "[diagram]"
    assert result.counters["media_placeholders"] == 1


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
    assert result.normalized_body_text == "[media][attachment]"
    assert result.counters["media_placeholders"] == 2
    assert "SECRET" not in str(result.warnings)


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


def test_result_repr_does_not_disclose_normalized_body() -> None:
    result = _normalize("<p>REVIEW_SENTINEL_SECRET</p>")
    assert "REVIEW_SENTINEL_SECRET" not in repr(result)
