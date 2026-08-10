from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.domain.models.drawio_xml import (
    DrawioXmlFailureCategory,
    DrawioXmlLimits,
    DrawioXmlProcessingError,
)
from knowledgenexus.foundation.infrastructure.processors.drawio_xml_processor import (
    DrawioXmlProcessor,
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
    return f"<mxCell {' '.join(attrs)}><mxGeometry/></mxCell>"


def test_drawio_extracts_nfc_labels_edges_and_container_context() -> None:
    body = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("10", value="Cafe\u0301", parent="1", vertex=True)
            + _cell("20", parent="1", vertex=True, value="Target")
            + _cell("30", parent="1", edge=True, source="10", target="20")
        )
    )

    result = DrawioXmlProcessor().process(body)

    assert result.node_count == 2
    assert result.edge_count == 1
    assert result.vertices[0].label == "Café"
    assert result.vertices[0].container_ids == ("0", "1")
    assert result.edges[0].source_id == "10"
    assert result.edges[0].target_id == "20"
    assert result.digest == hashlib.sha256(result.extracted_text.encode()).hexdigest()


def test_drawio_output_is_stable_across_xml_attribute_and_cell_order() -> None:
    first = _diagram(
        cells=(
            _cell("0", parent=None)
            + _cell("1", parent="0")
            + _cell("2", value="B", vertex=True)
            + _cell("3", value="A", vertex=True)
        )
    )
    second = _diagram(
        cells=(
            '<mxCell vertex="1" parent="1" value="A" id="3" />'
            '<mxCell id="1" parent="0" />'
            '<mxCell value="B" id="2" vertex="1" parent="1" />'
            '<mxCell id="0" />'
        )
    )

    left = DrawioXmlProcessor().process(first)
    right = DrawioXmlProcessor().process(second)

    assert left.extracted_text == right.extracted_text
    assert left.vertices == right.vertices
    assert left.edges == right.edges
    assert left.digest == right.digest
    assert left.byte_count != right.byte_count


@pytest.mark.parametrize(
    ("body", "category"),
    [
        (None, DrawioXmlFailureCategory.INVALID_INPUT),
        (object(), DrawioXmlFailureCategory.INVALID_INPUT),
        (b"<!DOCTYPE mxfile [<!ENTITY x 'boom'>]><mxfile />", DrawioXmlFailureCategory.XML_UNSAFE),
        (b"<not-mxfile />", DrawioXmlFailureCategory.STRUCTURE_INVALID),
        (b"<mxfile><diagram /></mxfile>", DrawioXmlFailureCategory.STRUCTURE_INVALID),
    ],
)
def test_drawio_rejects_malformed_or_unsafe_input(body: object, category: DrawioXmlFailureCategory) -> None:
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor().process(body)
    assert exc_info.value.category is category
    assert "boom" not in str(exc_info.value)


def test_drawio_enforces_byte_node_edge_depth_and_output_bounds() -> None:
    body = _diagram(cells=_cell("0", parent=None) + _cell("1", parent="0"))
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor(max_bytes=len(body) - 1).process(body)
    assert exc_info.value.category is DrawioXmlFailureCategory.BOUNDS_EXCEEDED

    many_nodes = _diagram(
        cells=_cell("0", parent=None)
        + _cell("1", parent="0")
        + _cell("2", parent="1", vertex=True, value="A")
        + _cell("3", parent="1", vertex=True, value="B")
    )
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor(max_nodes=1).process(many_nodes)
    assert exc_info.value.category is DrawioXmlFailureCategory.BOUNDS_EXCEEDED

    deep = _diagram(
        cells=_cell("0", parent=None)
        + _cell("1", parent="0")
        + '<mxCell id="2" parent="1" vertex="1" value="x"><mxGeometry><mxPoint><mxRectangle /></mxPoint></mxGeometry></mxCell>'
    )
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor(max_depth=4).process(deep)
    assert exc_info.value.category is DrawioXmlFailureCategory.BOUNDS_EXCEEDED

    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor(max_output_bytes=1).process(many_nodes)
    assert exc_info.value.category is DrawioXmlFailureCategory.BOUNDS_EXCEEDED


def test_drawio_rejects_unknown_attributes_and_impossible_links() -> None:
    unknown = _diagram(cells='<mxCell id="0" unknown="x" />')
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor().process(unknown)
    assert exc_info.value.category is DrawioXmlFailureCategory.STRUCTURE_INVALID

    dangling = _diagram(
        cells=_cell("0", parent=None)
        + _cell("1", parent="0")
        + _cell("2", parent="1", edge=True, source="missing", target="1")
    )
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor().process(dangling)
    assert exc_info.value.category is DrawioXmlFailureCategory.STRUCTURE_INVALID

    cycle = _diagram(cells='<mxCell id="0" parent="0" />')
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor().process(cycle)
    assert exc_info.value.category is DrawioXmlFailureCategory.STRUCTURE_INVALID


def test_drawio_forged_limits_and_forged_processor_fail_closed() -> None:
    forged_limits = object.__new__(DrawioXmlLimits)
    processor = DrawioXmlProcessor.__new__(DrawioXmlProcessor)
    processor._limits = forged_limits
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        processor.process(b"<mxfile />")
    assert exc_info.value.category is DrawioXmlFailureCategory.INVALID_INPUT


def test_drawio_unexpected_parser_exception_has_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_body: bytes) -> object:
        raise RuntimeError("secret/path")

    monkeypatch.setattr(
        "knowledgenexus.foundation.infrastructure.processors.drawio_xml_processor.ET.fromstring",
        _raise,
    )
    with pytest.raises(DrawioXmlProcessingError) as exc_info:
        DrawioXmlProcessor().process(b"<mxfile />")
    assert exc_info.value.category is DrawioXmlFailureCategory.INTERNAL_FAILURE
    assert exc_info.value.__suppress_context__ is True
    assert "secret" not in str(exc_info.value)
