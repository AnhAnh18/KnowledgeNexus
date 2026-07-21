from __future__ import annotations

import html.entities
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from urllib.parse import urlsplit

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluenceStorageNormalization,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceStorageNormalizationError,
    ConfluenceStorageNormalizerPort,
)

_AC_NAMESPACE = "urn:knowledgenexus:confluence:ac"
_RI_NAMESPACE = "urn:knowledgenexus:confluence:ri"
_FORBIDDEN_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_XML_LITERAL_SECTION = re.compile(r"<!\[CDATA\[.*?\]\]>|<!--.*?-->", re.DOTALL)
_NAMED_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]+);")
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_.+-]{0,63}$")
_SAFE_LANGUAGE = re.compile(r"^[A-Za-z0-9_+.-]{1,32}$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]+-[1-9][0-9]*$")
_BACKTICK_RUN = re.compile(r"`+")
_STANDARD_XML_ENTITIES = {"amp", "lt", "gt", "apos", "quot"}

_BLOCK_TAGS = {"article", "div", "section"}
_INLINE_CONTAINER_TAGS = {"span", "small", "sub", "sup"}
_ADMONITION_LABELS = {
    "info": "Info",
    "note": "Note",
    "tip": "Tip",
    "warning": "Warning",
    "panel": "Panel",
}
_DRAWIO_MACROS = {"drawio", "drawio-sketch", "drawio-board"}


class ConfluenceStorageXhtmlNormalizer(ConfluenceStorageNormalizerPort):
    """Convert one Confluence storage-format fragment into stable Markdown.

    The processor has no I/O and performs no external entity resolution. Its
    exceptions and warning records contain only fixed categories, sanitized
    element/macro names, and source-order ordinals.
    """

    def normalize(self, *, storage_xhtml: str) -> ConfluenceStorageNormalization:
        if not isinstance(storage_xhtml, str):
            raise TypeError("storage_xhtml expects str")
        if _contains_forbidden_declaration(storage_xhtml):
            raise ConfluenceStorageNormalizationError(
                "storage XHTML contains a forbidden declaration"
            )

        safe_fragment = _replace_named_entities(storage_xhtml)
        wrapped = (
            f'<m6c-root xmlns:ac="{_AC_NAMESPACE}" '
            f'xmlns:ri="{_RI_NAMESPACE}">{safe_fragment}</m6c-root>'
        )
        try:
            root = ET.fromstring(wrapped)
        except (ET.ParseError, ValueError) as exc:
            raise ConfluenceStorageNormalizationError(
                "storage XHTML is malformed"
            ) from exc

        renderer = _Renderer()
        rendered = renderer.render_children(root)
        normalized = _normalize_final_text(rendered)
        return ConfluenceStorageNormalization(
            normalized_body_text=normalized,
            counters=renderer.counters(),
            warnings=tuple(renderer.warnings),
        )


class _Renderer:
    def __init__(self) -> None:
        self.handled_macros: Counter[str] = Counter()
        self.unhandled_macros: Counter[str] = Counter()
        self.toc_dropped = 0
        self.media_placeholders = 0
        self.unsupported_elements = 0
        self.complex_tables = 0
        self.warnings: list[dict[str, object]] = []

    def counters(self) -> dict[str, object]:
        return {
            "handled_macros": dict(sorted(self.handled_macros.items())),
            "unhandled_macros": dict(sorted(self.unhandled_macros.items())),
            "toc_dropped": self.toc_dropped,
            "media_placeholders": self.media_placeholders,
            "unsupported_elements": self.unsupported_elements,
            "complex_tables": self.complex_tables,
        }

    def warn(self, code: str, name: str) -> None:
        self.warnings.append(
            {
                "code": code,
                "name": _sanitize_name(name),
                "ordinal": len(self.warnings) + 1,
            }
        )

    def render_children(self, element: ET.Element) -> str:
        parts: list[str] = []
        if element.text:
            parts.append(_escape_markdown_text(element.text))
        for child in element:
            parts.append(self.render(child))
            if child.tail:
                parts.append(_escape_markdown_text(child.tail))
        return "".join(parts)

    def render(self, element: ET.Element) -> str:
        name = _local_name(element.tag)

        if name in {"structured-macro", "macro"}:
            return self._render_macro(element)
        if name == "image" or name == "img":
            self.media_placeholders += 1
            return "[media]"
        if name == "link" and _has_descendant(element, "attachment"):
            self.media_placeholders += 1
            return "[attachment]"

        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            return f"\n\n{'#' * level} {self.render_children(element).strip()}\n\n"
        if name == "p":
            return f"\n\n{self.render_children(element).strip()}\n\n"
        if name == "br":
            return "\n"
        if name == "hr":
            return "\n\n---\n\n"
        if name in {"strong", "b"}:
            return f"**{self.render_children(element).strip()}**"
        if name in {"em", "i"}:
            return f"*{self.render_children(element).strip()}*"
        if name == "code":
            return _inline_code(_plain_text(element))
        if name == "pre":
            return _fenced_code(_plain_text(element))
        if name == "blockquote":
            return _blockquote(self.render_children(element))
        if name in {"ul", "ol"}:
            return self._render_list(element, ordered=name == "ol", depth=0)
        if name == "li":
            return self.render_children(element)
        if name == "table":
            return self._render_table(element)
        if name == "a":
            return self._render_link(element)
        if name in _BLOCK_TAGS:
            return f"\n\n{self.render_children(element)}\n\n"
        if name in _INLINE_CONTAINER_TAGS:
            return self.render_children(element)

        self.unsupported_elements += 1
        self.warn("unsupported_element", name)
        body = self.render_children(element).strip()
        if name in {"script", "style"}:
            return f"[unsupported:{_sanitize_name(name)} omitted]"
        if body:
            return body
        return f"[unsupported:{_sanitize_name(name)}]"

    def _render_link(self, element: ET.Element) -> str:
        label = self.render_children(element).strip() or "link"
        href = _attribute(element, "href")
        if not href:
            self.warn("link_target_missing", "a")
            return label
        if not _is_safe_link_target(href):
            self.warn("link_target_omitted", "a")
            return label
        target = href.replace(" ", "%20").replace(")", "\\)")
        return f"[{label}]({target})"

    def _render_list(self, element: ET.Element, *, ordered: bool, depth: int) -> str:
        lines: list[str] = []
        item_number = 1
        for child in element:
            if _local_name(child.tag) != "li":
                continue
            direct_parts: list[str] = []
            if child.text:
                direct_parts.append(_escape_markdown_text(child.text))
            nested: list[ET.Element] = []
            for item_child in child:
                child_name = _local_name(item_child.tag)
                if child_name in {"ul", "ol"}:
                    nested.append(item_child)
                else:
                    direct_parts.append(self.render(item_child))
                if item_child.tail:
                    direct_parts.append(_escape_markdown_text(item_child.tail))

            body = _single_line("".join(direct_parts))
            prefix = f"{item_number}. " if ordered else "- "
            indentation = "  " * depth
            lines.append(f"{indentation}{prefix}{body}".rstrip())
            for nested_list in nested:
                nested_rendered = self._render_list(
                    nested_list,
                    ordered=_local_name(nested_list.tag) == "ol",
                    depth=depth + 1,
                ).strip("\n")
                if nested_rendered:
                    lines.append(nested_rendered)
            item_number += 1
        return "\n\n" + "\n".join(lines) + "\n\n"

    def _render_table(self, element: ET.Element) -> str:
        rows = _table_rows(element)
        rendered_rows: list[list[str]] = []
        complex_shape = not rows
        expected_width: int | None = None

        for row in rows:
            cells = [child for child in row if _local_name(child.tag) in {"th", "td"}]
            if not cells:
                complex_shape = True
                continue
            if any(_has_span(cell) or _has_nested_table(cell) for cell in cells):
                complex_shape = True
            values = [
                _single_line(self.render_children(cell)).replace("|", "\\|")
                for cell in cells
            ]
            if expected_width is None:
                expected_width = len(values)
            elif len(values) != expected_width:
                complex_shape = True
            rendered_rows.append(values)

        if complex_shape or expected_width is None:
            self.complex_tables += 1
            self.warn("complex_table_fallback", "table")
            meaningful = [" | ".join(row) for row in rendered_rows if any(row)]
            if not meaningful:
                fallback = _single_line(self.render_children(element))
                meaningful = [fallback] if fallback else []
            return "\n\n[table]\n" + "\n".join(meaningful) + "\n\n"

        header = rendered_rows[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in rendered_rows[1:])
        return "\n\n" + "\n".join(lines) + "\n\n"

    def _render_macro(self, element: ET.Element) -> str:
        name = _sanitize_name(_attribute(element, "name") or "unknown")
        rich_body = _child(element, "rich-text-body")
        plain_body = _child(element, "plain-text-body")
        parameters = _parameters(element)

        if name == "code":
            self.handled_macros[name] += 1
            code = _plain_text(plain_body) if plain_body is not None else ""
            language = parameters.get("language", "")
            if language and not _SAFE_LANGUAGE.fullmatch(language):
                self.warn("macro_parameter_omitted", name)
                language = ""
            title = parameters.get("title", "").strip()
            title_line = f"**{_escape_markdown_text(title)}**\n\n" if title else ""
            return "\n\n" + title_line + _fenced_code(code, language=language).strip() + "\n\n"

        if name == "expand":
            self.handled_macros[name] += 1
            title = parameters.get("title", "").strip()
            body = self.render_children(rich_body) if rich_body is not None else ""
            title_line = f"**{_escape_markdown_text(title)}**\n\n" if title else ""
            return f"\n\n{title_line}{body}\n\n"

        if name == "excerpt":
            self.handled_macros[name] += 1
            return self.render_children(rich_body) if rich_body is not None else ""

        if name in {"include", "excerpt-include"}:
            self.handled_macros[name] += 1
            return "[included-page]"

        if name in _DRAWIO_MACROS:
            self.handled_macros[name] += 1
            self.media_placeholders += 1
            return "[diagram]"

        if name == "jira":
            self.handled_macros[name] += 1
            key = parameters.get("key", "").strip()
            if _JIRA_KEY.fullmatch(key):
                return key
            self.warn("macro_value_omitted", name)
            return "[jira-issue]"

        if name == "toc":
            self.handled_macros[name] += 1
            self.toc_dropped += 1
            return ""

        if name in _ADMONITION_LABELS:
            self.handled_macros[name] += 1
            body = self.render_children(rich_body) if rich_body is not None else ""
            body = _normalize_final_text(body)
            content = f"**{_ADMONITION_LABELS[name]}:**"
            if body:
                content = f"{content}\n{body}"
            return _blockquote(content)

        self.unhandled_macros[name] += 1
        self.warn("unhandled_macro", name)
        if rich_body is not None:
            body = self.render_children(rich_body).strip()
            if body:
                return f"\n\n[macro:{name}]\n\n{body}\n\n"
        return f"[macro:{name} omitted]"


def _replace_named_entities(fragment: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _STANDARD_XML_ENTITIES:
            return match.group(0)
        value = html.entities.html5.get(f"{name};")
        if value is None:
            raise ConfluenceStorageNormalizationError(
                "storage XHTML contains an unknown entity"
            )
        return "".join(f"&#x{ord(character):X};" for character in value)

    return _transform_outside_xml_literals(
        fragment,
        lambda value: _NAMED_ENTITY.sub(replace, value),
    )


def _contains_forbidden_declaration(fragment: str) -> bool:
    found = False

    def inspect(value: str) -> str:
        nonlocal found
        if _FORBIDDEN_DECLARATION.search(value):
            found = True
        return value

    _transform_outside_xml_literals(fragment, inspect)
    return found


def _transform_outside_xml_literals(
    fragment: str,
    transform: Callable[[str], str],
) -> str:
    parts: list[str] = []
    start = 0
    for match in _XML_LITERAL_SECTION.finditer(fragment):
        parts.append(transform(fragment[start : match.start()]))
        parts.append(match.group(0))
        start = match.end()
    parts.append(transform(fragment[start:]))
    return "".join(parts)


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return "unknown"
    return tag.rsplit("}", 1)[-1].lower()


def _sanitize_name(value: str) -> str:
    candidate = value.strip().lower()
    return candidate if _SAFE_NAME.fullmatch(candidate) else "unknown"


def _attribute(element: ET.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local_name(key) == name and isinstance(value, str):
            return value
    return None


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _has_descendant(element: ET.Element, name: str) -> bool:
    return any(_local_name(child.tag) == name for child in element.iter())


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element:
        if _local_name(child.tag) != "parameter":
            continue
        name = _sanitize_name(_attribute(child, "name") or "unknown")
        result[name] = _plain_text(child)
    return result


def _plain_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext())


def _table_rows(element: ET.Element) -> list[ET.Element]:
    rows: list[ET.Element] = []
    for child in element:
        name = _local_name(child.tag)
        if name == "tr":
            rows.append(child)
        elif name in {"thead", "tbody", "tfoot"}:
            rows.extend(row for row in child if _local_name(row.tag) == "tr")
    return rows


def _has_span(cell: ET.Element) -> bool:
    for name in ("rowspan", "colspan"):
        value = _attribute(cell, name)
        if value not in (None, "", "1"):
            return True
    return False


def _has_nested_table(cell: ET.Element) -> bool:
    return any(
        descendant is not cell and _local_name(descendant.tag) == "table"
        for descendant in cell.iter()
    )


def _escape_markdown_text(value: str) -> str:
    value = value.replace("\\", "\\\\")
    return re.sub(r"([*_])", r"\\\1", value)


def _inline_code(value: str) -> str:
    fence = _safe_backtick_fence(value)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def _fenced_code(value: str, *, language: str = "") -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    fence = _safe_backtick_fence(value)
    return f"\n\n{fence}{language}\n{value}\n{fence}\n\n"


def _safe_backtick_fence(value: str) -> str:
    longest = max((len(match.group(0)) for match in _BACKTICK_RUN.finditer(value)), default=0)
    return "`" * max(3, longest + 1)


def _blockquote(value: str) -> str:
    normalized = _normalize_final_text(value)
    if not normalized:
        return ""
    return "\n\n" + "\n".join(f"> {line}" if line else ">" for line in normalized.split("\n")) + "\n\n"


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_safe_link_target(value: str) -> bool:
    if any(character in value for character in "\r\n\x00"):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"", "http", "https", "mailto"}


def _normalize_final_text(value: str) -> str:
    value = unicodedata.normalize(
        "NFC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    )
    lines = [line.rstrip() for line in value.split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        blank = line == ""
        if blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = blank
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return "\n".join(collapsed)
