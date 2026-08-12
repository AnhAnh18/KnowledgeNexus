"""Bounded, offline draw.io XML extraction.

This module intentionally uses only :mod:`xml.etree.ElementTree`.  It never
loads a diagram engine, follows links, reads files, or performs network I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from knowledgenexus.foundation.domain.models.drawio_xml import (
    DrawioParseResult,
    DrawioXmlEdge,
    DrawioXmlFailureCategory,
    DrawioXmlLimits,
    DrawioXmlProcessingError,
    DrawioXmlVertex,
)


_UNSAFE_DECLARATION = re.compile(rb"<!\s*(?:doctype|entity|\[)", re.IGNORECASE)
_MAX_CELL_ID_BYTES = 512

# These cover mxCell attributes emitted by current diagrams.net releases.
# Unknown attributes are rejected so an unexpected XML shape does not silently
# become a different extraction contract.
_CELL_ATTRIBUTES = frozenset(
    {
        "id",
        "value",
        "label",
        "style",
        "vertex",
        "edge",
        "parent",
        "source",
        "target",
        "connectable",
        "visible",
        "collapsed",
        "html",
        "link",
        "tooltip",
        "placeholder",
        "movable",
        "resizable",
        "rotatable",
        "deletable",
        "cloneable",
        "swimlane",
        "startSize",
        "alternateBounds",
        "foldable",
        "container",
        "treeFoldingCode",
        "sourcePort",
        "targetPort",
        "entryX",
        "entryY",
        "entryDx",
        "entryDy",
        "exitX",
        "exitY",
        "exitDx",
        "exitDy",
    }
)
_DESCENDANT_ELEMENTS = frozenset({"mxGeometry", "mxPoint", "mxRectangle", "Array"})


def _fail(category: DrawioXmlFailureCategory) -> None:
    raise DrawioXmlProcessingError(category) from None


def _local_name(tag: object) -> str:
    if type(tag) is not str:
        _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
    # Namespaced draw.io content would make the accepted shape ambiguous.  The
    # canonical export uses unqualified mx* elements, so reject namespaces.
    if "}" in tag or ":" in tag:
        _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
    return tag


def _normalize_text(value: object, field: str, *, max_bytes: int, allow_empty: bool = True) -> str:
    if type(value) is not str:
        _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
    normalized = unicodedata.normalize("NFC", value)
    if not allow_empty and not normalized:
        _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
    if len(normalized.encode("utf-8")) > max_bytes:
        _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
    # XML 1.0 does not permit NUL/surrogates; reject them even when a forged
    # ElementTree node is supplied by a test or adapter.
    if any(
        ord(character) == 0
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in normalized
    ):
        _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
    return normalized


def _copy_limits(value: object) -> DrawioXmlLimits:
    if type(value) is not DrawioXmlLimits:
        _fail(DrawioXmlFailureCategory.INVALID_INPUT)
    try:
        if set(vars(value)) != {
            "max_bytes",
            "max_nodes",
            "max_edges",
            "max_depth",
            "max_output_bytes",
            "max_label_bytes",
        }:
            _fail(DrawioXmlFailureCategory.INVALID_INPUT)
        return DrawioXmlLimits(
            max_bytes=value.max_bytes,
            max_nodes=value.max_nodes,
            max_edges=value.max_edges,
            max_depth=value.max_depth,
            max_output_bytes=value.max_output_bytes,
            max_label_bytes=value.max_label_bytes,
        )
    except Exception:
        _fail(DrawioXmlFailureCategory.INVALID_INPUT)


class DrawioXmlProcessor:
    """Parse one already-materialized draw.io body deterministically."""

    def __init__(
        self,
        limits: object | None = None,
        *,
        max_bytes: int = DrawioXmlLimits.max_bytes,
        max_nodes: int = DrawioXmlLimits.max_nodes,
        max_edges: int = DrawioXmlLimits.max_edges,
        max_depth: int = DrawioXmlLimits.max_depth,
        max_output_bytes: int = DrawioXmlLimits.max_output_bytes,
        max_label_bytes: int = DrawioXmlLimits.max_label_bytes,
    ) -> None:
        if limits is not None:
            if any(
                value != default
                for value, default in (
                    (max_bytes, DrawioXmlLimits.max_bytes),
                    (max_nodes, DrawioXmlLimits.max_nodes),
                    (max_edges, DrawioXmlLimits.max_edges),
                    (max_depth, DrawioXmlLimits.max_depth),
                    (max_output_bytes, DrawioXmlLimits.max_output_bytes),
                    (max_label_bytes, DrawioXmlLimits.max_label_bytes),
                )
            ):
                _fail(DrawioXmlFailureCategory.INVALID_INPUT)
            self._limits = _copy_limits(limits)
            return
        try:
            self._limits = DrawioXmlLimits(
                max_bytes=max_bytes,
                max_nodes=max_nodes,
                max_edges=max_edges,
                max_depth=max_depth,
                max_output_bytes=max_output_bytes,
                max_label_bytes=max_label_bytes,
            )
        except Exception:
            _fail(DrawioXmlFailureCategory.INVALID_INPUT)

    def process(self, body: object) -> DrawioParseResult:
        """Return a bounded parse result or a category-only failure.

        The exact ``bytes`` check happens before any indexing or decoding, and
        the processor rebuilds its limits on every call to defend against
        forged/frozen dataclass instances.
        """

        try:
            limits = _copy_limits(self._limits)
            if type(body) is not bytes:
                _fail(DrawioXmlFailureCategory.INVALID_INPUT)
            if len(body) > limits.max_bytes:
                _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
            if _UNSAFE_DECLARATION.search(body) is not None:
                _fail(DrawioXmlFailureCategory.XML_UNSAFE)
            root = ET.fromstring(body)
            return self._extract(root, byte_count=len(body), limits=limits)
        except DrawioXmlProcessingError:
            raise
        except (ET.ParseError, UnicodeError):
            _fail(DrawioXmlFailureCategory.XML_INVALID)
        except Exception:
            # Do not expose parser internals, forged-object AttributeErrors, or
            # implementation details through this public boundary.
            _fail(DrawioXmlFailureCategory.INTERNAL_FAILURE)

    parse = process
    extract = process

    def _extract(
        self,
        root: object,
        *,
        byte_count: int,
        limits: DrawioXmlLimits,
    ) -> DrawioParseResult:
        if type(root) is not ET.Element:
            _fail(DrawioXmlFailureCategory.XML_INVALID)
        self._check_tree_bounds(root, limits)
        root_name = _local_name(root.tag)
        if root_name == "mxGraphModel":
            diagrams = (("diagram-1", root),)
        elif root_name == "mxfile":
            diagrams = self._read_mxfile(root)
        else:
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)

        vertices: list[DrawioXmlVertex] = []
        edges: list[DrawioXmlEdge] = []
        for diagram_id, graph_model in diagrams:
            graph_vertices, graph_edges = self._read_graph(
                graph_model, diagram_id=diagram_id, limits=limits
            )
            vertices.extend(graph_vertices)
            edges.extend(graph_edges)
        vertices.sort(key=lambda item: (item.diagram_id, item.cell_id))
        edges.sort(key=lambda item: (item.diagram_id, item.cell_id))
        if len(vertices) > limits.max_nodes or len(edges) > limits.max_edges:
            _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
        extracted_text = self._canonical_text(vertices, edges, limits)
        digest = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
        try:
            return DrawioParseResult(
                extracted_text=extracted_text,
                vertices=tuple(vertices),
                edges=tuple(edges),
                digest=digest,
                byte_count=byte_count,
                node_count=len(vertices),
                edge_count=len(edges),
            )
        except DrawioXmlProcessingError:
            raise
        except Exception:
            _fail(DrawioXmlFailureCategory.OUTPUT_INVALID)

    @staticmethod
    def _read_mxfile(root: ET.Element) -> tuple[tuple[str, ET.Element], ...]:
        diagrams: list[tuple[str, ET.Element]] = []
        seen_ids: set[str] = set()
        children = list(root)
        if not children:
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
        for index, diagram in enumerate(children, start=1):
            if _local_name(diagram.tag) != "diagram":
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            if diagram.text and diagram.text.strip():
                # Base64/deflate-compressed pages are intentionally outside
                # this source-first processor.
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            graph_models = [child for child in list(diagram) if _local_name(child.tag) == "mxGraphModel"]
            if len(graph_models) != 1 or len(list(diagram)) != 1:
                # Compressed/base64 pages and arbitrary children are outside
                # this source-first bounded processor.
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            raw_id = diagram.attrib.get("id") or diagram.attrib.get("name")
            diagram_id = raw_id if raw_id else f"diagram-{index}"
            diagram_id = _normalize_text(
                diagram_id,
                "diagram_id",
                max_bytes=_MAX_CELL_ID_BYTES,
                allow_empty=False,
            )
            if diagram_id in seen_ids:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            seen_ids.add(diagram_id)
            diagrams.append((diagram_id, graph_models[0]))
        # XML child order is not a deterministic identity; sorting by the
        # stable diagram ID makes repeated exports independent of page order.
        return tuple(sorted(diagrams, key=lambda item: item[0]))

    def _read_graph(
        self,
        graph_model: ET.Element,
        *,
        diagram_id: str,
        limits: DrawioXmlLimits,
    ) -> tuple[tuple[DrawioXmlVertex, ...], tuple[DrawioXmlEdge, ...]]:
        if _local_name(graph_model.tag) != "mxGraphModel":
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
        children = list(graph_model)
        roots = [child for child in children if _local_name(child.tag) == "root"]
        if len(roots) != 1 or len(children) != 1:
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
        cells = list(roots[0])
        if any(_local_name(cell.tag) != "mxCell" for cell in cells):
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
        if len(cells) > limits.max_nodes + limits.max_edges + 2:
            _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)

        by_id: dict[str, ET.Element] = {}
        for cell in cells:
            if set(cell.attrib) - _CELL_ATTRIBUTES:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            raw_id = cell.attrib.get("id")
            cell_id = _normalize_text(
                raw_id,
                "cell_id",
                max_bytes=_MAX_CELL_ID_BYTES,
                allow_empty=False,
            )
            if cell_id in by_id:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            by_id[cell_id] = cell
            self._validate_cell_descendants(cell)

        parent_by_id: dict[str, str | None] = {}
        for cell_id, cell in by_id.items():
            parent = cell.attrib.get("parent")
            if parent is not None:
                parent = _normalize_text(
                    parent,
                    "parent_id",
                    max_bytes=_MAX_CELL_ID_BYTES,
                    allow_empty=False,
                )
                if parent not in by_id:
                    _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            parent_by_id[cell_id] = parent

        # Validate every parent chain, including structural cells that do not
        # produce output records.  Memoization keeps this linear for deeply
        # nested container chains instead of repeatedly walking each prefix.
        ancestry_by_id = self._ancestry_map(parent_by_id, max_depth=limits.max_depth)

        vertices: list[DrawioXmlVertex] = []
        edges: list[DrawioXmlEdge] = []
        for cell_id, cell in by_id.items():
            vertex_flag = cell.attrib.get("vertex") == "1"
            edge_flag = cell.attrib.get("edge") == "1"
            if vertex_flag and edge_flag:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            if vertex_flag:
                raw_label = cell.attrib.get("value", cell.attrib.get("label", ""))
                label = _normalize_text(
                    raw_label,
                    "label",
                    max_bytes=limits.max_label_bytes,
                )
                vertices.append(
                    DrawioXmlVertex(
                        diagram_id=diagram_id,
                        cell_id=cell_id,
                        label=label,
                        container_ids=ancestry_by_id[cell_id],
                    )
                )
            elif edge_flag:
                source = cell.attrib.get("source")
                target = cell.attrib.get("target")
                for field, value in (("source_id", source), ("target_id", target)):
                    if value is not None:
                        value = _normalize_text(
                            value,
                            field,
                            max_bytes=_MAX_CELL_ID_BYTES,
                            allow_empty=False,
                        )
                        if value not in by_id:
                            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
                        if field == "source_id":
                            source = value
                        else:
                            target = value
                edges.append(
                    DrawioXmlEdge(
                        diagram_id=diagram_id,
                        cell_id=cell_id,
                        source_id=source,
                        target_id=target,
                        container_ids=ancestry_by_id[cell_id],
                    )
                )
        if len(vertices) > limits.max_nodes or len(edges) > limits.max_edges:
            _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
        return tuple(vertices), tuple(edges)

    @staticmethod
    def _validate_cell_descendants(cell: ET.Element) -> None:
        if cell.text and cell.text.strip():
            _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
        for child in cell.iter():
            if child is cell:
                continue
            if _local_name(child.tag) not in _DESCENDANT_ELEMENTS:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            if child.text and child.text.strip():
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            if child.tail and child.tail.strip():
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)

    @staticmethod
    def _ancestry_map(
        parent_by_id: dict[str, str | None],
        *,
        max_depth: int,
    ) -> dict[str, tuple[str, ...]]:
        cache: dict[str, tuple[str, ...]] = {}
        for start in parent_by_id:
            if start in cache:
                continue
            path: list[str] = []
            path_index: dict[str, int] = {}
            current: str | None = start
            while current is not None and current not in cache:
                if current in path_index:
                    _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
                path_index[current] = len(path)
                path.append(current)
                current = parent_by_id.get(current)
                if len(path) > max_depth + 1:
                    _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
            if current is not None and current in path_index:
                _fail(DrawioXmlFailureCategory.STRUCTURE_INVALID)
            for node in reversed(path):
                parent = parent_by_id.get(node)
                inherited = cache.get(parent, ()) if parent is not None else ()
                cache[node] = inherited + ((parent,) if parent is not None else ())
        return cache

    @staticmethod
    def _check_tree_bounds(root: ET.Element, limits: DrawioXmlLimits) -> None:
        stack: list[tuple[ET.Element, int]] = [(root, 1)]
        count = 0
        while stack:
            element, depth = stack.pop()
            count += 1
            if depth > limits.max_depth:
                _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
            if count > limits.max_nodes + limits.max_edges + limits.max_depth + 16:
                _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
            for child in list(element):
                stack.append((child, depth + 1))

    @staticmethod
    def _canonical_text(
        vertices: Iterable[DrawioXmlVertex],
        edges: Iterable[DrawioXmlEdge],
        limits: DrawioXmlLimits,
    ) -> str:
        records: list[str] = []
        for vertex in vertices:
            records.append(
                json.dumps(
                    {
                        "cell_id": vertex.cell_id,
                        "container_ids": list(vertex.container_ids),
                        "diagram_id": vertex.diagram_id,
                        "kind": "vertex",
                        "label": vertex.label,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        for edge in edges:
            records.append(
                json.dumps(
                    {
                        "cell_id": edge.cell_id,
                        "container_ids": list(edge.container_ids),
                        "diagram_id": edge.diagram_id,
                        "kind": "edge",
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        if not records:
            records.append('{"kind":"empty"}')
        output = unicodedata.normalize("NFC", "\n".join(records))
        if len(output.encode("utf-8")) > limits.max_output_bytes:
            _fail(DrawioXmlFailureCategory.BOUNDS_EXCEEDED)
        return output


__all__ = ["DrawioXmlProcessor"]
