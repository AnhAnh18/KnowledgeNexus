"""Tree-sitter backed C++/Java symbol extraction."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from tree_sitter import Language, Parser
import tree_sitter_cpp
import tree_sitter_java

from knowledgenexus.foundation.domain.models.symbol_index import (
    ParsedSymbol,
    SymbolParseResult,
    SymbolParseStatus,
)


_AGGREGATE_TYPES = {
    "class_specifier": "class",
    "struct_specifier": "struct",
    "enum_specifier": "enum",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "namespace_definition": "namespace",
    "package_declaration": "package",
}
_COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|\*/|#)")


class TreeSitterSymbolParser:
    """Extract the intentionally small MVP symbol vocabulary."""

    def __init__(self) -> None:
        self._languages = {
            "cpp": Language(tree_sitter_cpp.language()),
            "java": Language(tree_sitter_java.language()),
        }

    def parse(self, *, path: str, language: str, source_text: str) -> SymbolParseResult:
        if type(path) is not str or not path:
            raise TypeError("path is invalid")
        if language not in self._languages:
            raise ValueError("language is invalid")
        if type(source_text) is not str:
            raise TypeError("source_text is invalid")
        source_bytes = source_text.encode("utf-8")
        parser = Parser(self._languages[language])
        tree = parser.parse(source_bytes)
        error_count = sum(1 for node in self._walk(tree.root_node) if node.is_error or node.is_missing)
        status = SymbolParseStatus.PARTIAL if tree.root_node.has_error or error_count else SymbolParseStatus.OK
        symbols: list[ParsedSymbol] = []
        known_classes = self._known_class_names(tree.root_node, source_bytes, language)
        self._collect(
            node=tree.root_node,
            source_bytes=source_bytes,
            source_text=source_text,
            path=path,
            language=language,
            status=status,
            parents=(),
            known_classes=known_classes,
            output=symbols,
        )
        if language == "java":
            package = next((item for item in symbols if item.symbol_type == "package"), None)
            if package is not None:
                for index, item in enumerate(symbols):
                    if item.symbol_type == "package":
                        continue
                    parent = item.parent_qualified_name
                    qualified = f"{package.qualified_name}::{item.qualified_name}"
                    if parent is None:
                        parent = package.qualified_name
                    else:
                        parent = f"{package.qualified_name}::{parent}"
                    symbols[index] = replace(item, qualified_name=qualified, parent_qualified_name=parent)
        symbols.sort(key=lambda item: (item.start_byte, item.end_byte, item.qualified_name, item.symbol_type))
        return SymbolParseResult(
            path=path,
            language=language,
            status=status,
            symbols=tuple(symbols),
            error_count=error_count,
        )

    def _collect(
        self,
        *,
        node: object,
        source_bytes: bytes,
        source_text: str,
        path: str,
        language: str,
        status: SymbolParseStatus,
        parents: tuple[ParsedSymbol, ...],
        known_classes: frozenset[str],
        output: list[ParsedSymbol],
    ) -> None:
        function_name, qualifier = self._function_name_and_qualifier(node, source_bytes, language)
        symbol_type = self._symbol_type(node, language, parents, qualifier, known_classes, function_name)
        current_parents = parents
        if symbol_type is not None:
            name = function_name or self._name(node, source_bytes, language)
            if name:
                qualified_name = self._qualified_name(name, parents)
                parent_qualified_name = parents[-1].qualified_name if parents else None
                if qualifier:
                    qualified_name = f"{qualifier}::{name}"
                    parent_qualified_name = qualifier if symbol_type == "method" else self._namespace_parent(qualifier)
                start_row = node.start_point[0]
                end_row = node.end_point[0]
                leading_comment, comment_row = self._leading_comment(source_text, start_row)
                body = node.child_by_field_name("body")
                signature_end = body.start_byte if body is not None else node.end_byte
                signature = source_bytes[node.start_byte:signature_end].decode("utf-8", "strict").strip()
                aggregate = symbol_type in {"class", "struct", "interface", "enum", "namespace", "package"}
                parsed = ParsedSymbol(
                    path=path,
                    language=language,
                    symbol_type=symbol_type,
                    name=name,
                    qualified_name=qualified_name,
                    signature=signature or None,
                    line_start=comment_row + 1 if comment_row is not None else start_row + 1,
                    line_end=max(start_row + 1, end_row + 1),
                    parent_qualified_name=parent_qualified_name,
                    leading_comment=leading_comment,
                    parse_status=status,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    body_start_byte=body.start_byte if body is not None else None,
                    aggregate=aggregate,
                )
                output.append(parsed)
                current_parents = parents + (parsed,)
        for child in node.named_children:
            self._collect(
                node=child,
                source_bytes=source_bytes,
                source_text=source_text,
                path=path,
                language=language,
                status=status,
                parents=current_parents,
                known_classes=known_classes,
                output=output,
            )

    @staticmethod
    def _symbol_type(
        node: object,
        language: str,
        parents: tuple[ParsedSymbol, ...],
        qualifier: str | None,
        known_classes: frozenset[str],
        function_name: str | None,
    ) -> str | None:
        node_type = node.type
        if node_type in _AGGREGATE_TYPES:
            return _AGGREGATE_TYPES[node_type]
        if language == "cpp" and (
            node_type == "function_definition"
            or (node_type in {"declaration", "field_declaration"} and function_name is not None)
        ):
            if parents and parents[-1].symbol_type in {"class", "struct"}:
                return "method"
            if qualifier and qualifier in known_classes:
                return "method"
            return "function"
        if language == "java" and node_type in {"method_declaration", "constructor_declaration"}:
            return "method"
        return None

    @staticmethod
    def _name(node: object, source_bytes: bytes, language: str) -> str | None:
        named = node.child_by_field_name("name")
        if named is None and node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            named = TreeSitterSymbolParser._function_name_node(declarator)
        if named is None and node.type == "package_declaration":
            raw = source_bytes[node.start_byte:node.end_byte].decode("utf-8", "strict")
            raw = raw.removeprefix("package").strip().rstrip(";").strip()
            return raw or None
        if named is None:
            return None
        value = source_bytes[named.start_byte:named.end_byte].decode("utf-8", "strict").strip()
        return value or None

    @staticmethod
    def _function_name_and_qualifier(
        node: object, source_bytes: bytes, language: str
    ) -> tuple[str | None, str | None]:
        if language != "cpp" or node.type not in {"function_definition", "declaration", "field_declaration"}:
            return None, None
        declarator = node.child_by_field_name("declarator")
        while declarator is not None and declarator.type == "function_declarator":
            declarator = declarator.child_by_field_name("declarator")
        if declarator is None:
            return None, None
        raw = source_bytes[declarator.start_byte:declarator.end_byte].decode("utf-8", "strict").strip()
        if "::" in raw:
            qualifier, name = raw.rsplit("::", 1)
            return name.strip(), qualifier.strip()
        if declarator.type in {"identifier", "field_identifier", "type_identifier", "operator_name", "destructor_name"}:
            return raw, None
        found = TreeSitterSymbolParser._function_name_node(declarator)
        if found is None:
            return None, None
        return source_bytes[found.start_byte:found.end_byte].decode("utf-8", "strict").strip(), None

    @staticmethod
    def _namespace_parent(qualifier: str) -> str | None:
        return qualifier.rsplit("::", 1)[0] if "::" in qualifier else None

    def _known_class_names(self, root: object, source_bytes: bytes, language: str) -> frozenset[str]:
        if language != "cpp":
            return frozenset()
        found: set[str] = set()

        def walk(node: object, parents: tuple[str, ...]) -> None:
            next_parents = parents
            if node.type == "namespace_definition":
                name = self._name(node, source_bytes, language)
                if name:
                    next_parents = parents + (name,)
            elif node.type in {"class_specifier", "struct_specifier"}:
                name = self._name(node, source_bytes, language)
                if name:
                    qualified = "::".join((*parents, name))
                    found.add(qualified)
                    next_parents = parents + (name,)
            for child in node.named_children:
                walk(child, next_parents)

        walk(root, ())
        return frozenset(found)

    @staticmethod
    def _find_name_node(node: object | None) -> object | None:
        if node is None:
            return None
        if node.type in {"identifier", "field_identifier", "type_identifier", "operator_name", "destructor_name"}:
            return node
        for child in reversed(node.named_children):
            found = TreeSitterSymbolParser._find_name_node(child)
            if found is not None:
                return found
        return None

    @staticmethod
    def _function_name_node(node: object | None) -> object | None:
        if node is None:
            return None
        direct = node.child_by_field_name("declarator")
        if direct is not None:
            return TreeSitterSymbolParser._function_name_node(direct)
        if node.type in {"identifier", "field_identifier", "operator_name", "destructor_name"}:
            return node
        return TreeSitterSymbolParser._find_name_node(node)

    @staticmethod
    def _qualified_name(name: str, parents: tuple[ParsedSymbol, ...]) -> str:
        return f"{parents[-1].qualified_name}::{name}" if parents else name

    @staticmethod
    def _leading_comment(source_text: str, start_row: int) -> tuple[str, int | None]:
        lines = source_text.split("\n")
        if start_row <= 0:
            return "", None
        cursor = start_row - 1
        selected: list[str] = []
        while cursor >= 0 and _COMMENT_LINE.match(lines[cursor]):
            selected.append(lines[cursor])
            cursor -= 1
        selected.reverse()
        if not selected:
            return "", None
        return "\n".join(selected).strip(), cursor + 1

    @staticmethod
    def _walk(node: object) -> Iterable[object]:
        yield node
        for child in node.named_children:
            yield from TreeSitterSymbolParser._walk(child)


__all__ = ["TreeSitterSymbolParser"]
