from __future__ import annotations

from knowledgenexus.foundation.domain.models.symbol_index import (
    ParsedSymbol,
)
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


class SymbolRecordBuilder:
    """Build a schema-shaped SymbolRecord without owning parsing or I/O."""

    @classmethod
    def build(
        cls,
        *,
        symbol: ParsedSymbol,
        repo: str,
        branch: str,
        commit_hash: str,
        scanned_at: str,
        symbol_id: str,
        chunk_id: str | None,
        schema_validator: object,
    ) -> dict[str, object]:
        if type(symbol) is not ParsedSymbol:
            raise TypeError("symbol is invalid")
        ParsedSymbol.__post_init__(symbol)
        values = {"repo": repo, "branch": branch, "commit_hash": commit_hash, "scanned_at": scanned_at, "symbol_id": symbol_id}
        if any(type(value) is not str or not value for value in values.values()):
            raise TypeError("record identity is invalid")
        if chunk_id is not None and (type(chunk_id) is not str or not chunk_id):
            raise TypeError("chunk_id is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "symbol_id": symbol_id,
            "repo": repo,
            "branch": branch,
            "commit_hash": commit_hash,
            "file_path": symbol.path,
            "language": symbol.language,
            "symbol_type": symbol.symbol_type,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "line_start": symbol.line_start,
            "line_end": symbol.line_end,
            "parse_status": symbol.parse_status.value,
            "scanned_at": scanned_at,
        }
        if symbol.signature is not None:
            record["signature"] = symbol.signature
        if symbol.parent_qualified_name is not None:
            record["parent_symbol"] = symbol.parent_qualified_name
        if chunk_id is not None:
            record["chunk_id"] = chunk_id
        schema_validator.validate_record("SymbolRecord", record)
        return dict(record)


__all__ = ["SymbolRecordBuilder"]
