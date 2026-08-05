import pytest

from knowledgenexus.foundation.domain.models.symbol_index import (
    GitSymbolIndexFailureCategory,
    GitSymbolIndexMetrics,
    GitSymbolIndexResult,
    GitSymbolIndexStatus,
    ParsedSymbol,
    SymbolParseStatus,
)
from knowledgenexus.foundation.domain.rules.symbol_id_generator import SymbolIdGenerator


def _symbol() -> ParsedSymbol:
    return ParsedSymbol(
        path="src/a.cpp",
        language="cpp",
        symbol_type="function",
        name="f",
        qualified_name="f",
        signature="void f()",
        line_start=1,
        line_end=1,
        parent_qualified_name=None,
        leading_comment="",
        parse_status=SymbolParseStatus.OK,
        start_byte=0,
        end_byte=8,
    )


def test_symbol_id_overload_suffix_is_stable() -> None:
    value = SymbolIdGenerator.generate(
        repo="spen-sdk",
        branch="develop",
        file_path="src/a.cpp",
        qualified_name="f",
        signature="void f(int)",
        overloaded=True,
    )
    assert value.endswith("f~" + __import__("hashlib").sha256(b"void f(int)").hexdigest()[:8])


def test_failed_result_rejects_partial_payload() -> None:
    with pytest.raises(ValueError):
        GitSymbolIndexResult(
            status=GitSymbolIndexStatus.FAILED,
            symbol_records=({"symbol_id": "x"},),
            error_category=GitSymbolIndexFailureCategory.PARSER_FAILED,
        )


def test_metrics_reject_impossible_counts() -> None:
    with pytest.raises(ValueError):
        GitSymbolIndexMetrics(
            authority_file_count=1,
            symbol_count=2,
            chunk_count=1,
            partial_file_count=0,
            fallback_file_count=0,
            oversized_part_count=0,
        )
