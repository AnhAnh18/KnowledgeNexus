"""Convert raw draw.io XML to Mermaid flowchart syntax.

Reads directly from the XML source to extract vertex labels, edge labels
(which the canonical-text extractor omits), and container nesting.  The
output is a human-readable ``.mmd`` file written alongside the packet.

This module intentionally uses only :mod:`xml.etree.ElementTree` and
applies the same safety pre-checks as the draw.io XML processor.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from html import unescape

from knowledgenexus.foundation.domain.models.drawio_xml import (
    DrawioXmlLimits,
    DrawioXmlProcessingError,
)
from knowledgenexus.foundation.infrastructure.processors.drawio_xml_processor import (
    DrawioXmlProcessor,
)

_HTML_TAG = re.compile(r"<[^>]+>")
_NON_IDENT = re.compile(r"[^a-zA-Z0-9_]")


class DrawioMermaidConversionError(Exception):
    """Raised when raw XML cannot be converted to Mermaid syntax."""


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    cleaned = _HTML_TAG.sub("", cleaned)
    return unescape(cleaned).strip()


def _safe_id(cell_id: str, id_map: dict[str, str], taken: set[str]) -> str:
    if cell_id in id_map:
        return id_map[cell_id]
    sanitized = _NON_IDENT.sub("_", cell_id)
    if not sanitized or not sanitized[0].isalpha():
        sanitized = f"n{sanitized}"
    candidate = sanitized
    seq = 0
    while candidate in taken:
        seq += 1
        candidate = f"{sanitized}_{seq}"
    id_map[cell_id] = candidate
    taken.add(candidate)
    return candidate


def _escape_label(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', "&quot;").replace("\n", "<br/>")


def _render_diagram(
    graph_model: ET.Element,
    *,
    diagram_name: str | None,
    multi_page: bool,
) -> str | None:
    if graph_model.tag != "mxGraphModel":
        return None
    root_children = list(graph_model)
    roots = [c for c in root_children if c.tag == "root"]
    if len(roots) != 1:
        return None

    vertex_ids: set[str] = set()
    vertex_labels: dict[str, str] = {}
    vertex_parents: dict[str, str | None] = {}
    edge_list: list[tuple[str, str | None, str | None, str]] = []
    all_ids: set[str] = set()
    for cell in roots[0]:
        if cell.tag != "mxCell":
            continue
        cid = cell.attrib.get("id", "")
        parent = cell.attrib.get("parent")
        is_vertex = cell.attrib.get("vertex") == "1"
        is_edge = cell.attrib.get("edge") == "1"
        raw_label = cell.attrib.get("value", cell.attrib.get("label", ""))
        label = _strip_html(raw_label) if raw_label else ""
        all_ids.add(cid)
        if is_vertex:
            vertex_ids.add(cid)
            vertex_labels[cid] = label
            vertex_parents[cid] = parent
        elif is_edge:
            source = cell.attrib.get("source")
            target = cell.attrib.get("target")
            edge_list.append((cid, source, target, label))

    if not vertex_ids and not edge_list:
        return None

    structural = all_ids - vertex_ids - {e[0] for e in edge_list}
    children_of: dict[str, list[str]] = defaultdict(list)
    for vid in sorted(vertex_ids):
        p = vertex_parents[vid]
        if p is not None:
            children_of[p].append(vid)
    containers = {vid for vid in vertex_ids if vid in children_of}

    id_map: dict[str, str] = {}
    taken: set[str] = set()
    lines: list[str] = []
    if multi_page and diagram_name:
        lines.append(f"%% {diagram_name}")
    lines.append("flowchart TD")

    rendered: set[str] = set()

    def render_vertex(vid: str, indent: int) -> None:
        if vid in rendered:
            return
        rendered.add(vid)
        prefix = "    " * indent
        safe = _safe_id(vid, id_map, taken)
        if vid in containers:
            label = _escape_label(vertex_labels[vid]) if vertex_labels[vid] else safe
            lines.append(f'{prefix}subgraph {safe}["{label}"]')
            for child_id in children_of[vid]:
                render_vertex(child_id, indent + 1)
            lines.append(f"{prefix}end")
        else:
            if vertex_labels[vid]:
                label = _escape_label(vertex_labels[vid])
                lines.append(f'{prefix}{safe}["{label}"]')
            else:
                lines.append(f"{prefix}{safe}")

    top_level = sorted(
        vid for vid in vertex_ids
        if vertex_parents[vid] in structural or vertex_parents[vid] is None
    )
    for vid in top_level:
        render_vertex(vid, 1)
    for vid in sorted(vertex_ids):
        if vid not in rendered:
            render_vertex(vid, 1)

    for _eid, source, target, label in sorted(edge_list, key=lambda e: e[0]):
        if source is None or target is None:
            continue
        if source not in vertex_ids or target not in vertex_ids:
            continue
        src = _safe_id(source, id_map, taken)
        tgt = _safe_id(target, id_map, taken)
        if label:
            lines.append(f'    {src} -->|"{_escape_label(label)}"| {tgt}')
        else:
            lines.append(f"    {src} --> {tgt}")

    return "\n".join(lines)


def convert_drawio_to_mermaid(body: object) -> str:
    """Convert raw draw.io XML bytes to Mermaid flowchart syntax.

    Multi-page diagrams produce multiple flowcharts separated by blank
    lines.  Raises :class:`DrawioMermaidConversionError` on invalid input.
    """
    # Reuse the canonical processor as the single structural and resource-limit
    # boundary.  It rejects wrong runtime types, unsafe declarations, unknown
    # shapes, duplicate IDs, invalid references, parent cycles, excessive
    # depth/cell counts, and oversized labels before this renderer touches any
    # fields or performs output work.
    try:
        DrawioXmlProcessor().process(body)
    except DrawioXmlProcessingError:
        raise DrawioMermaidConversionError("draw.io XML rejected") from None

    assert type(body) is bytes  # established by DrawioXmlProcessor
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, UnicodeError):
        raise DrawioMermaidConversionError("draw.io XML rejected") from None

    diagrams: list[tuple[str | None, ET.Element]] = []
    if root.tag == "mxGraphModel":
        diagrams.append((None, root))
    elif root.tag == "mxfile":
        for child in root:
            if child.tag != "diagram":
                continue
            name = child.attrib.get("name") or child.attrib.get("id")
            graph_models = [gc for gc in child if gc.tag == "mxGraphModel"]
            if len(graph_models) == 1:
                diagrams.append((name, graph_models[0]))
    else:
        raise DrawioMermaidConversionError("not a draw.io file")

    if not diagrams:
        raise DrawioMermaidConversionError("no diagrams found")

    multi = len(diagrams) > 1
    parts: list[str] = []
    for name, gm in diagrams:
        rendered = _render_diagram(gm, diagram_name=name, multi_page=multi)
        if rendered:
            parts.append(rendered)

    if not parts:
        raise DrawioMermaidConversionError("no renderable content")

    output = "\n\n".join(parts) + "\n"
    if len(output.encode("utf-8")) > DrawioXmlLimits.max_output_bytes:
        raise DrawioMermaidConversionError("Mermaid output exceeds size limit")
    return output


__all__ = ["DrawioMermaidConversionError", "convert_drawio_to_mermaid"]
