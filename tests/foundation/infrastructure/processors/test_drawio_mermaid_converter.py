from __future__ import annotations

import pytest

from knowledgenexus.foundation.infrastructure.processors.drawio_mermaid_converter import (
    DrawioMermaidConversionError,
    convert_drawio_to_mermaid,
)


def _diagram(*, cells: str, diagram_id: str = "page") -> bytes:
    return (
        f'<mxfile><diagram id="{diagram_id}"><mxGraphModel><root>{cells}'
        "</root></mxGraphModel></diagram></mxfile>"
    ).encode("utf-8")


def _cell(
    cell_id: str,
    *,
    value: str = "",
    parent: str | None = "1",
    vertex: bool = False,
    edge: bool = False,
    source: str | None = None,
    target: str | None = None,
) -> str:
    attrs = [f'id="{cell_id}"']
    if value:
        attrs.append(f'value="{value}"')
    if parent is not None:
        attrs.append(f'parent="{parent}"')
    if vertex:
        attrs.append('vertex="1"')
    if edge:
        attrs.append('edge="1"')
    if source is not None:
        attrs.append(f'source="{source}"')
    if target is not None:
        attrs.append(f'target="{target}"')
    return f"<mxCell {' '.join(attrs)} />"


def test_vertices_produce_mermaid_nodes() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="Start", parent="1", vertex=True)
            + _cell("B", value="End", parent="1", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert "flowchart TD" in result
    assert 'A["Start"]' in result
    assert 'B["End"]' in result


def test_edge_labels_are_extracted() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="Yes?", parent="1", vertex=True)
            + _cell("B", value="Done", parent="1", vertex=True)
            + _cell("E1", value="approved", parent="1", edge=True, source="A", target="B")
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'A -->|"approved"| B' in result


def test_edge_without_label() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("X", value="From", parent="1", vertex=True)
            + _cell("Y", value="To", parent="1", vertex=True)
            + _cell("E", parent="1", edge=True, source="X", target="Y")
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert "X --> Y" in result
    assert '-->|' not in result


def test_container_becomes_subgraph() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("C", value="Group", parent="1", vertex=True)
            + _cell("A", value="Inside", parent="C", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'subgraph C["Group"]' in result
    assert 'A["Inside"]' in result
    assert "end" in result


def test_nested_containers() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("outer", value="Outer", parent="1", vertex=True)
            + _cell("inner", value="Inner", parent="outer", vertex=True)
            + _cell("leaf", value="Leaf", parent="inner", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'subgraph outer["Outer"]' in result
    assert 'subgraph inner["Inner"]' in result
    assert 'leaf["Leaf"]' in result


def test_multi_page_diagram() -> None:
    page1 = (
        '<diagram id="p1" name="Login Flow"><mxGraphModel><root>'
        + _cell("0", parent=None)
        + _cell("1", parent="0")
        + _cell("A", value="Login", parent="1", vertex=True)
        + "</root></mxGraphModel></diagram>"
    )
    page2 = (
        '<diagram id="p2" name="Logout Flow"><mxGraphModel><root>'
        + _cell("0", parent=None)
        + _cell("1", parent="0")
        + _cell("B", value="Logout", parent="1", vertex=True)
        + "</root></mxGraphModel></diagram>"
    )
    body = f"<mxfile>{page1}{page2}</mxfile>".encode("utf-8")

    result = convert_drawio_to_mermaid(body)

    assert "%% Login Flow" in result
    assert "%% Logout Flow" in result
    assert result.count("flowchart TD") == 2
    assert 'A["Login"]' in result
    assert 'B["Logout"]' in result


def test_html_labels_stripped() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("H", value="&lt;b&gt;Bold&lt;/b&gt; text", parent="1", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'H["Bold text"]' in result


def test_standalone_mxgraphmodel() -> None:
    body = (
        "<mxGraphModel><root>"
        + _cell("0", parent=None)
        + _cell("1", parent="0")
        + _cell("N", value="Node", parent="1", vertex=True)
        + "</root></mxGraphModel>"
    ).encode("utf-8")

    result = convert_drawio_to_mermaid(body)

    assert "flowchart TD" in result
    assert 'N["Node"]' in result


def test_dangling_edge_skipped() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="Only", parent="1", vertex=True)
            + _cell("E", parent="1", edge=True, source="A")
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'A["Only"]' in result
    assert "-->" not in result


def test_empty_diagram_raises() -> None:
    body = (
        "<mxfile><diagram id='p'><mxGraphModel><root>"
        "<mxCell id='0' /><mxCell id='1' parent='0' />"
        "</root></mxGraphModel></diagram></mxfile>"
    ).encode("utf-8")

    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


def test_invalid_xml_raises() -> None:
    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(b"not xml at all")


def test_unsafe_declaration_raises() -> None:
    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(b"<!DOCTYPE mxfile [<!ENTITY x 'boom'>]><mxfile />")


def test_non_drawio_root_raises() -> None:
    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(b"<html><body>hi</body></html>")


@pytest.mark.parametrize("body", ("<mxfile />", None, object(), bytearray(b"<mxfile />")))
def test_non_bytes_raises(body: object) -> None:
    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


def test_duplicate_cell_id_raises() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="One", parent="1", vertex=True)
            + _cell("A", value="Two", parent="1", vertex=True)
        )
    )

    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


def test_parent_cycle_raises() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="A", parent="B", vertex=True)
            + _cell("B", value="B", parent="A", vertex=True)
        )
    )

    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


def test_unknown_cell_attribute_raises() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + '<mxCell id="A" parent="1" vertex="1" unexpected="value" />'
        )
    )

    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


@pytest.mark.parametrize(
    "invalid_cell",
    (
        '<mxCell parent="1" vertex="1" />',
        '<mxCell id="A" parent="1" vertex="1" edge="1" />',
        '<mxCell id="A" parent="1" vertex="true" />',
    ),
)
def test_missing_or_impossible_cell_flags_raise(invalid_cell: str) -> None:
    body = _diagram(
        cells=_cell("0", parent=None) + _cell("1", parent="0") + invalid_cell,
    )

    with pytest.raises(DrawioMermaidConversionError):
        convert_drawio_to_mermaid(body)


def test_quotes_are_escaped_as_mermaid_html_entities() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="&quot;quoted&quot;", parent="1", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert 'A["&quot;quoted&quot;"]' in result


def test_vertex_without_label() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("X", parent="1", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert "flowchart TD" in result
    # Node rendered without label brackets
    lines = result.strip().splitlines()
    node_lines = [l.strip() for l in lines if "X" in l and "flowchart" not in l]
    assert any(l == "X" for l in node_lines)


def test_output_ends_with_newline() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("A", value="N", parent="1", vertex=True)
        )
    )

    result = convert_drawio_to_mermaid(body)

    assert result.endswith("\n")
