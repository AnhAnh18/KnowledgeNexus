from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.domain.models.drawio_xml import (
    DrawioParseResult,
    DrawioXmlEdge,
    DrawioXmlFailureCategory,
    DrawioXmlProcessingError,
    DrawioXmlVertex,
)


def _result() -> DrawioParseResult:
    vertex = DrawioXmlVertex("page", "2", "Label", ("0", "1"))
    edge = DrawioXmlEdge("page", "3", "2", "2", ("0", "1"))
    text = '{"cell_id":"2","container_ids":["0","1"],"diagram_id":"page","kind":"vertex","label":"Label"}\n{"cell_id":"3","container_ids":["0","1"],"diagram_id":"page","kind":"edge","source_id":"2","target_id":"2"}'
    return DrawioParseResult(
        extracted_text=text,
        vertices=(vertex,),
        edges=(edge,),
        digest=hashlib.sha256(text.encode()).hexdigest(),
        byte_count=10,
        node_count=1,
        edge_count=1,
    )


def test_drawio_result_rejects_impossible_counters_and_digest() -> None:
    result = _result()
    with pytest.raises(ValueError):
        DrawioParseResult(
            extracted_text=result.extracted_text,
            vertices=result.vertices,
            edges=result.edges,
            digest=result.digest,
            byte_count=result.byte_count,
            node_count=2,
            edge_count=result.edge_count,
        )
    with pytest.raises(ValueError):
        DrawioParseResult(
            extracted_text=result.extracted_text,
            vertices=result.vertices,
            edges=result.edges,
            digest="0" * 64,
            byte_count=result.byte_count,
            node_count=result.node_count,
            edge_count=result.edge_count,
        )


def test_drawio_result_rebuilds_forged_nested_values_before_field_access() -> None:
    forged_vertex = object.__new__(DrawioXmlVertex)
    forged_edge = object.__new__(DrawioXmlEdge)
    text = ""
    with pytest.raises(ValueError):
        DrawioParseResult(
            extracted_text=text,
            vertices=(forged_vertex,),
            edges=(forged_edge,),
            digest=hashlib.sha256(text.encode()).hexdigest(),
            byte_count=0,
            node_count=1,
            edge_count=1,
        )


def test_drawio_failure_category_is_closed_and_sanitized() -> None:
    with pytest.raises(TypeError):
        DrawioXmlProcessingError("secret/path")
    error = DrawioXmlProcessingError(DrawioXmlFailureCategory.XML_UNSAFE)
    assert str(error) == "xml_unsafe"
    assert "secret" not in repr(error)
