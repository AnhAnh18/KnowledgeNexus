from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.git_code_source import CodeDocumentPlan, GitFileObservation
from knowledgenexus.foundation.domain.models.symbol_index import (
    BuildGitSymbolsRequest,
    GitSymbolIndexFailureCategory,
    GitSymbolIndexMetrics,
    GitSymbolIndexResult,
    GitSymbolIndexStatus,
    ParsedSymbol,
    SymbolParseResult,
    SymbolParseStatus,
)
from knowledgenexus.foundation.domain.records.chunk_record_builder import ChunkRecordBuilder
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.foundation.domain.rules.symbol_id_generator import SymbolIdGenerator
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules
from knowledgenexus.foundation.domain.rules.symbol_record_builder import SymbolRecordBuilder
from knowledgenexus.foundation.ports.symbol_parser_port import SymbolParserPort
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


_ACTIVE_CHUNKER_VERSION = "1.3.0"
_AUTHORITY_EXTENSIONS = frozenset({".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".java"})
_LANGUAGE_BY_EXTENSION = {
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".h": "cpp", ".hh": "cpp",
    ".hpp": "cpp", ".hxx": "cpp", ".inl": "cpp", ".java": "java",
}
_CHUNK_ID = re.compile(r"^chunk:git:[0-9a-f]{16}(?:-[0-9]+)?$")


class BuildGitSymbols:
    """Build an atomic authority-symbol stream from an approved M9-B plan."""

    def __init__(
        self,
        *,
        parser: SymbolParserPort,
        tokenizer: TokenizerPort,
        schema_validator: object | None = None,
    ) -> None:
        if not callable(getattr(parser, "parse", None)):
            raise TypeError("parser is invalid")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer is invalid")
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._parser = parser
        self._tokenizer = tokenizer
        self._validator = validator

    def execute(self, request: object) -> GitSymbolIndexResult:
        try:
            self._validate_request(request)
            assert type(request) is BuildGitSymbolsRequest
            observations = self._authority_observations(request.plan)
            records: list[dict[str, object]] = []
            chunks: list[dict[str, object]] = []
            seen_chunk_ids: dict[str, str] = {}
            partial_files = 0
            fallback_files = 0
            oversized_parts = 0
            for observation in observations:
                suffix = "." + observation.path.rsplit(".", 1)[-1].lower() if "." in observation.path else ""
                language = _LANGUAGE_BY_EXTENSION.get(suffix)
                if language is None:
                    continue
                parsed = self._parser.parse(
                    path=observation.path,
                    language=language,
                    source_text=observation.normalized_text,
                )
                if type(parsed) is not SymbolParseResult:
                    raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
                SymbolParseResult.__post_init__(parsed)
                if parsed.path != observation.path or parsed.language != language:
                    raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
                self._validate_parsed_symbols(parsed, observation)
                if parsed.status is SymbolParseStatus.PARTIAL:
                    partial_files += 1
                symbols = self._dedupe_symbols(parsed.symbols)
                if not symbols:
                    fallback_files += 1
                    file_chunks = self._build_fallback_windows(observation, request.chunking_profile, request.plan)
                    self._append_chunks(chunks, file_chunks, seen_chunk_ids)
                    continue
                grouped: dict[str, list[ParsedSymbol]] = defaultdict(list)
                for symbol in symbols:
                    grouped[symbol.qualified_name].append(symbol)
                symbol_ids: dict[int, str] = {}
                for symbol in symbols:
                    overloaded = len(grouped[symbol.qualified_name]) > 1
                    if overloaded and len({item.signature for item in grouped[symbol.qualified_name]}) != len(grouped[symbol.qualified_name]):
                        raise _Failure(GitSymbolIndexFailureCategory.RESULT_INVALID)
                    symbol_ids[id(symbol)] = SymbolIdGenerator.generate(
                        repo=request.plan.repo_name,
                        branch=request.plan.branch,
                        file_path=symbol.path,
                        qualified_name=symbol.qualified_name,
                        signature=symbol.signature,
                        overloaded=overloaded,
                    )
                for symbol in parsed.symbols:
                    symbol_id = symbol_ids[id(symbol)]
                    rendered = self._render_symbol(symbol, symbols, observation.normalized_text)
                    parts = self._split_symbol(
                        rendered=rendered,
                        symbol=symbol,
                        observation=observation,
                        profile=request.chunking_profile,
                        plan=request.plan,
                        all_symbols=symbols,
                    )
                    if len(parts) > 1:
                        oversized_parts += len(parts)
                    first_chunk_id: str | None = None
                    for part_index, (text, line_start, line_end, unit_key) in enumerate(parts):
                        chunk = self._build_chunk(
                            text=text,
                            unit_key=unit_key,
                            symbol=symbol,
                            line_start=line_start,
                            line_end=line_end,
                            part_index=part_index if len(parts) > 1 else None,
                            part_total=len(parts) if len(parts) > 1 else None,
                            observation=observation,
                            profile=request.chunking_profile,
                            plan=request.plan,
                        )
                        chunk_id = chunk["chunk_id"]
                        if type(chunk_id) is not str or _CHUNK_ID.fullmatch(chunk_id) is None:
                            raise _Failure(GitSymbolIndexFailureCategory.RESULT_INVALID)
                        if first_chunk_id is None:
                            first_chunk_id = chunk_id
                        self._append_chunks(chunks, [chunk], seen_chunk_ids)
                    if first_chunk_id is None:
                        raise _Failure(GitSymbolIndexFailureCategory.RESULT_INVALID)
                    records.append(
                        SymbolRecordBuilder.build(
                            symbol=symbol,
                            repo=request.plan.repo_name,
                            branch=request.plan.branch,
                            commit_hash=request.plan.commit_sha,
                            scanned_at=request.scanned_at,
                            symbol_id=symbol_id,
                            chunk_id=first_chunk_id,
                            schema_validator=self._validator,
                        )
                    )
            records.sort(key=lambda value: (value["file_path"], value["line_start"], value["symbol_id"]))
            chunks.sort(key=lambda value: (value["file_path"], value.get("line_start", 0), value["chunk_id"]))
            metrics = GitSymbolIndexMetrics(
                authority_file_count=len(observations),
                symbol_count=len(records),
                chunk_count=len(chunks),
                partial_file_count=partial_files,
                fallback_file_count=fallback_files,
                oversized_part_count=oversized_parts,
            )
            return GitSymbolIndexResult(
                status=GitSymbolIndexStatus.SUCCESS,
                symbol_records=tuple(records),
                chunks=tuple(chunks),
                metrics=metrics,
            )
        except _Failure as exc:
            return GitSymbolIndexResult(status=GitSymbolIndexStatus.FAILED, error_category=exc.category)
        except Exception:
            return GitSymbolIndexResult(status=GitSymbolIndexStatus.FAILED, error_category=GitSymbolIndexFailureCategory.INTERNAL_FAILURE)

    def _validate_request(self, request: object) -> None:
        if type(request) is not BuildGitSymbolsRequest:
            raise _Failure(GitSymbolIndexFailureCategory.INVALID_REQUEST)
        try:
            BuildGitSymbolsRequest.__post_init__(request)
        except Exception as exc:
            raise _Failure(GitSymbolIndexFailureCategory.INVALID_REQUEST) from exc
        if request.chunking_profile.chunker_version != _ACTIVE_CHUNKER_VERSION:
            raise _Failure(GitSymbolIndexFailureCategory.INVALID_REQUEST)
        if not callable(getattr(self._parser, "parse", None)) or not callable(getattr(self._tokenizer, "tokenize", None)):
            raise _Failure(GitSymbolIndexFailureCategory.INVALID_DEPENDENCY)

    @staticmethod
    def _authority_observations(plan: CodeDocumentPlan) -> tuple[GitFileObservation, ...]:
        canonical = {item.path: item for item in plan.observations}
        result: list[GitFileObservation] = []
        for item in plan.authority_observations:
            expected = canonical.get(item.path)
            if expected is None or expected != item or not item.symbol_authority:
                raise _Failure(GitSymbolIndexFailureCategory.PLAN_INVALID)
            suffix = "." + item.path.rsplit(".", 1)[-1].lower() if "." in item.path else ""
            if suffix not in _AUTHORITY_EXTENSIONS:
                raise _Failure(GitSymbolIndexFailureCategory.PLAN_INVALID)
            result.append(item)
        return tuple(result)

    @staticmethod
    def _dedupe_symbols(symbols: tuple[ParsedSymbol, ...]) -> tuple[ParsedSymbol, ...]:
        selected: dict[tuple[str, str], ParsedSymbol] = {}
        for symbol in symbols:
            key = (symbol.qualified_name, BuildGitSymbols._canonical_signature(symbol.signature))
            previous = selected.get(key)
            if previous is None or (previous.body_start_byte is None and symbol.body_start_byte is not None):
                selected[key] = symbol
        return tuple(sorted(selected.values(), key=lambda item: (item.start_byte, item.end_byte, item.qualified_name)))

    @staticmethod
    def _canonical_signature(signature: str | None) -> str:
        if signature is None:
            return ""
        value = re.sub(r"\b(?:[A-Za-z_]\w*::)+(?=[~A-Za-z_]\w*\s*\()", "", signature)
        value = re.sub(r"\s+[A-Za-z_]\w*(?=[,)])", "", value)
        return re.sub(r"\s+", "", value).rstrip(";")

    @staticmethod
    def _validate_parsed_symbols(parsed: SymbolParseResult, observation: GitFileObservation) -> None:
        source_bytes = observation.normalized_text.encode("utf-8")
        line_count = max(1, len(observation.normalized_text.split("\n")))

        def line_for(offset: int, *, end: bool = False) -> int:
            prefix = source_bytes[:offset]
            line = prefix.count(b"\n") + 1
            if end and offset > 0 and offset <= len(source_bytes) and source_bytes[offset - 1 : offset] == b"\n":
                line -= 1
            return max(1, line)

        for symbol in parsed.symbols:
            if symbol.path != observation.path or symbol.language not in {"cpp", "java"}:
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
            if not (1 <= symbol.line_start <= symbol.line_end <= line_count):
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
            if not (0 <= symbol.start_byte < symbol.end_byte <= len(source_bytes)):
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
            start_line = line_for(symbol.start_byte)
            end_line = line_for(symbol.end_byte, end=True)
            if not (symbol.line_start <= start_line <= symbol.line_end):
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
            if not (symbol.line_start <= end_line <= symbol.line_end):
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)
            if symbol.body_start_byte is not None and not (
                symbol.start_byte <= symbol.body_start_byte <= symbol.end_byte
            ):
                raise _Failure(GitSymbolIndexFailureCategory.PARSER_RESULT_INVALID)

    def _render_symbol(self, symbol: ParsedSymbol, all_symbols: tuple[ParsedSymbol, ...], source_text: str) -> str:
        header, body_lines, _ = self._render_components(symbol, all_symbols, source_text)
        return TextNormalizationRules.normalize_text(header + "\n\n" + "\n".join(body_lines))

    def _split_symbol(self, *, rendered: str, symbol: ParsedSymbol, observation: GitFileObservation, profile: ChunkingProfile, plan: CodeDocumentPlan, all_symbols: tuple[ParsedSymbol, ...]) -> list[tuple[str, int, int, str]]:
        count = self._token_count(rendered)
        if count <= profile.hard_maximum_tokens:
            return [(rendered, symbol.line_start, symbol.line_end, self._unit_key(symbol))]
        header, lines, source_start = self._render_components(symbol, all_symbols, observation.normalized_text)
        parts: list[tuple[str, int, int, str]] = []
        cursor = 0
        while cursor < len(lines):
            end = cursor
            best = None
            while end < len(lines) and end - cursor < profile.code_window_max_lines:
                candidate = header + "\n\n" + "\n".join(lines[cursor : end + 1])
                if self._token_count(candidate) > profile.hard_maximum_tokens:
                    break
                best = end + 1
                end += 1
            if best is None:
                raise _Failure(GitSymbolIndexFailureCategory.UNSPLITTABLE_CODE_LINE)
            part_text = TextNormalizationRules.normalize_text(header + "\n\n" + "\n".join(lines[cursor:best]))
            line_start = min(source_start + cursor, symbol.line_end)
            line_end = min(source_start + best - 1, symbol.line_end)
            if line_end < line_start:
                line_start, line_end = symbol.line_start, symbol.line_end
            parts.append((part_text, line_start, line_end, f"{self._unit_key(symbol)}#p{len(parts)}"))
            if best >= len(lines):
                break
            cursor = max(cursor + 1, best - profile.code_window_overlap_lines)
        return parts

    def _render_components(
        self,
        symbol: ParsedSymbol,
        all_symbols: tuple[ParsedSymbol, ...],
        source_text: str,
    ) -> tuple[str, list[str], int]:
        prefix = f"// spen-sdk \u00b7 {symbol.path} \u00b7 {symbol.qualified_name}"
        header = prefix + ("\n\n" + symbol.leading_comment if symbol.leading_comment else "")
        if symbol.aggregate:
            body_lines = [symbol.signature or symbol.name]
            body_lines.extend(
                child.signature
                for child in all_symbols
                if child.parent_qualified_name == symbol.qualified_name and child.signature
            )
            return header, body_lines, symbol.line_start
        source_lines = source_text.split("\n")
        comment_line_count = symbol.leading_comment.count("\n") + 1 if symbol.leading_comment else 0
        source_start = symbol.line_start + comment_line_count
        return header, source_lines[source_start - 1 : symbol.line_end], source_start

    def _build_fallback_windows(self, observation: GitFileObservation, profile: ChunkingProfile, plan: CodeDocumentPlan) -> list[dict[str, object]]:
        lines = observation.normalized_text.split("\n")
        output: list[dict[str, object]] = []
        cursor = 0
        while cursor < len(lines):
            end = cursor
            best = None
            while end < len(lines) and end - cursor < profile.code_window_max_lines:
                candidate = self._prefix(observation.path) + "\n\n" + "\n".join(lines[cursor : end + 1])
                if self._token_count(candidate) > profile.hard_maximum_tokens:
                    break
                best = end + 1
                end += 1
            if best is None:
                raise _Failure(GitSymbolIndexFailureCategory.UNSPLITTABLE_CODE_LINE)
            text = self._prefix(observation.path) + "\n\n" + "\n".join(lines[cursor:best])
            output.append({
                "text": TextNormalizationRules.normalize_text(text),
                "unit_key": f"{observation.path}#w{len(output)}",
                "line_start": cursor + 1,
                "line_end": best,
            })
            if best >= len(lines):
                break
            cursor = max(cursor + 1, best - profile.code_window_overlap_lines)
        total = len(output)
        return [
            self._build_chunk(
                text=item["text"],
                unit_key=item["unit_key"],
                symbol=None,
                line_start=item["line_start"],
                line_end=item["line_end"],
                part_index=index,
                part_total=total,
                observation=observation,
                profile=profile,
                plan=plan,
                content_kind="code_window",
            )
            for index, item in enumerate(output)
        ]

    def _build_chunk(self, *, text: str, unit_key: str, symbol: ParsedSymbol | None, line_start: int, line_end: int, part_index: int | None, part_total: int | None, observation: GitFileObservation, profile: ChunkingProfile, plan: CodeDocumentPlan, content_kind: str = "code_symbol") -> dict[str, object]:
        text = TextNormalizationRules.normalize_text(text)
        token_count = self._token_count(text)
        document_id = f"git:spen-sdk:{observation.path}"
        chunk_id = ChunkIdGenerator.generate_chunk_id("git", f"git:spen-sdk:{observation.path}", unit_key, text)
        record = ChunkRecordBuilder.build(
            chunk_id=chunk_id,
            document_id=document_id,
            source_system="git",
            source_type="code_file",
            text=text,
            content_kind=content_kind,
            language=_LANGUAGE_BY_EXTENSION["." + observation.path.rsplit(".", 1)[-1].lower()],
            token_count=token_count,
            acl_tags=["repo:spen-sdk"],
            chunker_version=profile.chunker_version,
            heading_path=[],
            repo=plan.repo_name,
            branch=plan.branch,
            file_path=observation.path,
            symbol=symbol.qualified_name if symbol is not None else None,
            line_start=line_start,
            line_end=line_end,
            part_index=part_index,
            part_total=part_total,
            jira_keys=[],
            relation_ids=[],
            source_version=plan.commit_sha,
        )
        self._validator.validate_record("ChunkRecord", record)
        if record.get("token_count") != token_count or record.get("source_version") != plan.commit_sha:
            raise _Failure(GitSymbolIndexFailureCategory.RESULT_INVALID)
        return record

    @staticmethod
    def _append_chunks(target: list[dict[str, object]], new_chunks: list[dict[str, object]], seen: dict[str, str]) -> None:
        for chunk in new_chunks:
            chunk_id = chunk["chunk_id"]
            preimage = repr((chunk_id, chunk["text"], chunk.get("file_path"), chunk.get("symbol")))
            if chunk_id in seen and seen[chunk_id] != preimage:
                raise _Failure(GitSymbolIndexFailureCategory.CHUNK_ID_COLLISION)
            if chunk_id in seen:
                raise _Failure(GitSymbolIndexFailureCategory.CHUNK_ID_COLLISION)
            seen[chunk_id] = preimage
            target.append(chunk)

    @staticmethod
    def _unit_key(symbol: ParsedSymbol) -> str:
        return symbol.qualified_name

    def _token_count(self, text: str) -> int:
        try:
            result = self._tokenizer.tokenize(text=text)
            return result.token_count
        except Exception as exc:
            raise _Failure(GitSymbolIndexFailureCategory.TOKENIZER_FAILED) from exc

    @staticmethod
    def _prefix(path: str) -> str:
        return f"// spen-sdk \u00b7 {path}"


class _Failure(Exception):
    def __init__(self, category: GitSymbolIndexFailureCategory) -> None:
        self.category = category


__all__ = ["BuildGitSymbols"]
