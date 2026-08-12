from knowledgenexus.foundation.infrastructure.parsers import TreeSitterSymbolParser
from knowledgenexus.foundation.domain.models import SymbolParseStatus


def test_extracts_cpp_namespace_class_and_method_deterministically() -> None:
    source = """// class docs
namespace outer {\nclass Widget {\npublic:\n  // method docs\n  void run(int value) { return; }\n};\n}\n"""
    result = TreeSitterSymbolParser().parse(path="src/widget.cpp", language="cpp", source_text=source)
    assert result.status is SymbolParseStatus.OK
    assert [(item.symbol_type, item.qualified_name) for item in result.symbols] == [
        ("namespace", "outer"),
        ("class", "outer::Widget"),
        ("method", "outer::Widget::run"),
    ]
    assert result.symbols[-1].leading_comment == "// method docs"
    assert result.symbols[-1].line_start == 5


def test_extracts_java_package_and_method() -> None:
    source = "package demo.core;\npublic class Service {\n  void start() {}\n}\n"
    result = TreeSitterSymbolParser().parse(path="src/Service.java", language="java", source_text=source)
    assert [(item.symbol_type, item.qualified_name) for item in result.symbols] == [
        ("package", "demo.core"),
        ("class", "demo.core::Service"),
        ("method", "demo.core::Service::start"),
    ]


def test_error_tree_is_partial_without_aborting() -> None:
    result = TreeSitterSymbolParser().parse(
        path="src/broken.cpp",
        language="cpp",
        source_text="namespace broken { class Missing { void f( {\n",
    )
    assert result.status is SymbolParseStatus.PARTIAL
    assert result.error_count > 0


def test_cpp_declarations_and_qualified_definitions_have_complete_identity() -> None:
    source = """namespace n {
class A { public: A(); void f(int); };
void g();
}
void n::A::f(int value) {}
void n::A::A() {}
void n::g();
"""
    result = TreeSitterSymbolParser().parse(path="src/a.cpp", language="cpp", source_text=source)
    values = [(item.symbol_type, item.name, item.qualified_name, item.parent_qualified_name) for item in result.symbols]
    assert ("method", "A", "n::A::A", "n::A") in values
    assert ("method", "f", "n::A::f", "n::A") in values
    assert ("function", "g", "n::g", "n") in values
    assert all(item.qualified_name != "f" for item in result.symbols)
