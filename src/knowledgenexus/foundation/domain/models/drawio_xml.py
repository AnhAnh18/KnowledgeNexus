"""Immutable, metadata-safe values returned by the offline draw.io parser.

The draw.io processor deliberately keeps its result independent from the
``MediaAsset`` contract.  The application boundary can project this result
into a media asset and an extraction-detail projection without making XML
structure part of the public schema.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


_SHA256_LENGTH = 64
_MAX_TEXT_BYTES = 256 * 1024 * 1024
_MAX_ID_BYTES = 512


class DrawioXmlFailureCategory(StrEnum):
    """Stable categories exposed by the draw.io processing boundary."""

    INVALID_INPUT = "invalid_input"
    XML_INVALID = "xml_invalid"
    XML_UNSAFE = "xml_unsafe"
    STRUCTURE_INVALID = "structure_invalid"
    BOUNDS_EXCEEDED = "bounds_exceeded"
    OUTPUT_INVALID = "output_invalid"
    INTERNAL_FAILURE = "internal_failure"


class DrawioXmlProcessingError(Exception):
    """Sanitized draw.io processing failure.

    Only an allowlisted category is accepted.  In particular, callers cannot
    smuggle arbitrary parser/engine text through this exception boundary.
    """

    def __init__(self, category: DrawioXmlFailureCategory) -> None:
        if type(category) is not DrawioXmlFailureCategory:
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category.value!r})"


def _text(value: object, field: str, *, allow_empty: bool = True) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if not allow_empty and not normalized:
        raise ValueError(f"{field} is invalid")
    if len(normalized.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} is invalid")
    # XML labels may contain line breaks, but NUL and surrogate code points
    # cannot be represented safely in the extracted UTF-8 output.
    if any(
        ord(character) == 0
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in normalized
    ):
        raise ValueError(f"{field} is invalid")
    return normalized


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, allow_empty=False)
    if len(normalized.encode("utf-8")) > _MAX_ID_BYTES:
        raise ValueError(f"{field} is invalid")
    if any(
        ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        or character in ("\u2028", "\u2029")
        for character in normalized
    ):
        raise ValueError(f"{field} is invalid")
    return normalized


@dataclass(frozen=True, repr=False)
class DrawioXmlLimits:
    """Resource limits used by :class:`DrawioXmlProcessor`.

    Limits are immutable and validated at construction.  The processor also
    rebuilds this value before use so forged instances fail closed.
    """

    max_bytes: int = 4 * 1024 * 1024
    max_nodes: int = 10_000
    max_edges: int = 20_000
    max_depth: int = 64
    max_output_bytes: int = 1 * 1024 * 1024
    max_label_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_bytes,
            self.max_nodes,
            self.max_edges,
            self.max_depth,
            self.max_output_bytes,
            self.max_label_bytes,
        )
        if any(type(value) is not int for value in values):
            raise TypeError("draw.io limits are invalid")
        if not 1 <= self.max_bytes <= 256 * 1024 * 1024:
            raise ValueError("max_bytes is invalid")
        if not 1 <= self.max_nodes <= 1_000_000:
            raise ValueError("max_nodes is invalid")
        if not 0 <= self.max_edges <= 2_000_000:
            raise ValueError("max_edges is invalid")
        if not 1 <= self.max_depth <= 1024:
            raise ValueError("max_depth is invalid")
        if not 1 <= self.max_output_bytes <= 256 * 1024 * 1024:
            raise ValueError("max_output_bytes is invalid")
        if not 1 <= self.max_label_bytes <= 256 * 1024 * 1024:
            raise ValueError("max_label_bytes is invalid")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class DrawioXmlVertex:
    """A labelled draw.io vertex and its parent/container ancestry."""

    diagram_id: str
    cell_id: str
    label: str
    container_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagram_id", _identifier(self.diagram_id, "diagram_id"))
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        if type(self.container_ids) is not tuple or any(
            type(item) is not str for item in self.container_ids
        ):
            raise TypeError("container_ids are invalid")
        normalized = tuple(_identifier(item, "container_id") for item in self.container_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("container_ids are invalid")
        object.__setattr__(self, "container_ids", normalized)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    @property
    def id(self) -> str:
        return self.cell_id

    @property
    def containers(self) -> tuple[str, ...]:
        return self.container_ids


@dataclass(frozen=True, repr=False)
class DrawioXmlEdge:
    """A draw.io edge link and its parent/container ancestry."""

    diagram_id: str
    cell_id: str
    source_id: str | None
    target_id: str | None
    container_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagram_id", _identifier(self.diagram_id, "diagram_id"))
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        for field in ("source_id", "target_id"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _identifier(value, field))
        if type(self.container_ids) is not tuple or any(
            type(item) is not str for item in self.container_ids
        ):
            raise TypeError("container_ids are invalid")
        normalized = tuple(_identifier(item, "container_id") for item in self.container_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("container_ids are invalid")
        object.__setattr__(self, "container_ids", normalized)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    @property
    def id(self) -> str:
        return self.cell_id

    @property
    def source(self) -> str | None:
        return self.source_id

    @property
    def target(self) -> str | None:
        return self.target_id

    @property
    def containers(self) -> tuple[str, ...]:
        return self.container_ids


@dataclass(frozen=True, repr=False)
class DrawioParseResult:
    """Deterministic, bounded draw.io extraction output."""

    extracted_text: str
    vertices: tuple[DrawioXmlVertex, ...]
    edges: tuple[DrawioXmlEdge, ...]
    digest: str
    byte_count: int
    node_count: int
    edge_count: int

    def __post_init__(self) -> None:
        try:
            if set(vars(self)) != {
                "extracted_text",
                "vertices",
                "edges",
                "digest",
                "byte_count",
                "node_count",
                "edge_count",
            }:
                raise ValueError("draw.io result is invalid")
        except TypeError:
            raise ValueError("draw.io result is invalid") from None
        text = _text(self.extracted_text, "extracted_text")
        if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
            raise ValueError("extracted_text is invalid")
        if type(self.vertices) is not tuple or any(
            type(item) is not DrawioXmlVertex for item in self.vertices
        ):
            raise TypeError("vertices are invalid")
        if type(self.edges) is not tuple or any(
            type(item) is not DrawioXmlEdge for item in self.edges
        ):
            raise TypeError("edges are invalid")
        # Rebuild nested values before accessing fields so a forged dataclass
        # cannot produce an unsanitized AttributeError at this boundary.
        try:
            vertices = tuple(
                DrawioXmlVertex(
                    diagram_id=item.diagram_id,
                    cell_id=item.cell_id,
                    label=item.label,
                    container_ids=item.container_ids,
                )
                for item in self.vertices
            )
            edges = tuple(
                DrawioXmlEdge(
                    diagram_id=item.diagram_id,
                    cell_id=item.cell_id,
                    source_id=item.source_id,
                    target_id=item.target_id,
                    container_ids=item.container_ids,
                )
                for item in self.edges
            )
        except Exception:
            raise ValueError("draw.io result is invalid") from None
        if type(self.digest) is not str or len(self.digest) != _SHA256_LENGTH:
            raise ValueError("digest is invalid")
        try:
            int(self.digest, 16)
        except (TypeError, ValueError):
            raise ValueError("digest is invalid") from None
        for field in ("byte_count", "node_count", "edge_count"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} is invalid")
        if self.byte_count > 256 * 1024 * 1024:
            raise ValueError("byte_count is invalid")
        if self.node_count != len(vertices) or self.edge_count != len(edges):
            raise ValueError("draw.io counters are invalid")
        if vertices != tuple(sorted(vertices, key=lambda item: (item.diagram_id, item.cell_id))):
            raise ValueError("vertices are not deterministic")
        if edges != tuple(sorted(edges, key=lambda item: (item.diagram_id, item.cell_id))):
            raise ValueError("edges are not deterministic")
        expected_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self.digest != expected_digest:
            raise ValueError("digest does not match extracted_text")
        object.__setattr__(self, "extracted_text", text)
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "edges", edges)

    @property
    def labels(self) -> tuple[str, ...]:
        """Convenience projection used by media application code."""

        return tuple(vertex.label for vertex in self.vertices if vertex.label)

    @property
    def text(self) -> str:
        """Alias for callers that use the generic processor result protocol."""

        return self.extracted_text

    @property
    def content_hash(self) -> str:
        return self.digest

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


# Short aliases make the draw.io result convenient without introducing names
# that collide with the shared PDF/OCR processing models.
DrawioVertex = DrawioXmlVertex
DrawioEdge = DrawioXmlEdge
DrawioXmlParseResult = DrawioParseResult


__all__ = [
    "DrawioEdge",
    "DrawioParseResult",
    "DrawioVertex",
    "DrawioXmlEdge",
    "DrawioXmlFailureCategory",
    "DrawioXmlLimits",
    "DrawioXmlParseResult",
    "DrawioXmlProcessingError",
    "DrawioXmlVertex",
]
