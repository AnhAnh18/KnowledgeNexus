from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.confluence_chunking import (
    ChunkingResult,
    ConfluenceChunkingError,
    ConfluenceChunkingFailureCategory,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiCodeBlock,
    WikiDocumentStructure,
    WikiProseBlock,
    WikiSection,
    WikiTableBlock,
)
from knowledgenexus.foundation.domain.rules.text_normalization import (
    TextNormalizationRules,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationValidationError,
)


_BREADCRUMB_SEPARATOR = " › "
_DOCUMENT_ROOT = object()
_PARAGRAPH_BOUNDARY = re.compile(r"\n{2}")
_SENTENCE_BOUNDARY = re.compile(r"[.!?。！？](?:\s+|$)")


class _ChunkIdGenerator(Protocol):
    def generate_chunk_id(
        self,
        source_system: str,
        document_stable_key: str,
        unit_key: str,
        normalized_text: str,
    ) -> str: ...


class _ChunkRecordBuilder(Protocol):
    def build(self, **fields: object) -> dict[str, object]: ...


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


@dataclass(frozen=True, repr=False)
class _SectionView:
    section: WikiSection
    parent_identity: object
    prose_only_body: str | None
    is_empty: bool


@dataclass(frozen=True, repr=False)
class _Candidate:
    kind: str
    breadcrumb: str
    heading_path: tuple[str, ...]
    body: str
    unit_key: str
    code_block: WikiCodeBlock | None = None
    table_block: WikiTableBlock | None = None


@dataclass(frozen=True, repr=False)
class _Part:
    kind: str
    breadcrumb: str
    heading_path: tuple[str, ...]
    body: str
    unit_key: str
    part_index: int | None = None
    part_total: int | None = None


@dataclass(frozen=True, repr=False)
class _SourceRange:
    start: int
    end: int


@dataclass
class _MetricState:
    sections_merged: int = 0
    oversize_splits: int = 0
    empty_sections_skipped: int = 0
    prose_split_units: int = 0
    table_split_units: int = 0
    code_split_units: int = 0
    overlap_windows: int = 0
    tokenizer_boundary_fallbacks: int = 0


def _fail(category: ConfluenceChunkingFailureCategory) -> None:
    raise ConfluenceChunkingError(category) from None


class BuildConfluenceChunks:
    """Build deterministic Confluence ChunkRecords from approved M6D-C input."""

    def __init__(
        self,
        *,
        profile: ChunkingProfile,
        tokenizer: TokenizerPort,
        chunk_id_generator: _ChunkIdGenerator,
        chunk_record_builder: _ChunkRecordBuilder,
        schema_validator: _SchemaValidator,
    ) -> None:
        if not isinstance(profile, ChunkingProfile):
            raise TypeError("profile expects ChunkingProfile")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer expects TokenizerPort")
        if not callable(getattr(chunk_id_generator, "generate_chunk_id", None)):
            raise TypeError("chunk_id_generator is invalid")
        if not callable(getattr(chunk_record_builder, "build", None)):
            raise TypeError("chunk_record_builder is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._profile = profile
        self._tokenizer = tokenizer
        self._chunk_id_generator = chunk_id_generator
        self._chunk_record_builder = chunk_record_builder
        self._schema_validator = schema_validator

    def execute(
        self,
        *,
        canonical_document: Mapping[str, object],
        structure: WikiDocumentStructure,
    ) -> ChunkingResult:
        try:
            return self._execute(
                canonical_document=canonical_document,
                structure=structure,
            )
        except ConfluenceChunkingError:
            raise
        except Exception:
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)

    def _execute(
        self,
        *,
        canonical_document: Mapping[str, object],
        structure: WikiDocumentStructure,
    ) -> ChunkingResult:
        self._validate_inputs(canonical_document, structure)
        state = _MetricState()
        candidates = self._assemble_candidates(structure, state)
        parts: list[_Part] = []
        for candidate in candidates:
            parts.extend(self._split_candidate(candidate, state))
        records, token_counts = self._build_records(
            canonical_document=canonical_document,
            parts=parts,
        )
        return ChunkingResult(
            records=tuple(records),
            metrics=self._metrics(records, token_counts, state),
        )

    def _validate_inputs(
        self,
        canonical_document: Mapping[str, object],
        structure: WikiDocumentStructure,
    ) -> None:
        if not isinstance(canonical_document, Mapping):
            _fail(
                ConfluenceChunkingFailureCategory.CANONICAL_DOCUMENT_VALIDATION_FAILED
            )
        if not isinstance(structure, WikiDocumentStructure):
            _fail(
                ConfluenceChunkingFailureCategory.DOCUMENT_STRUCTURE_IDENTITY_MISMATCH
            )
        title = canonical_document.get("title")
        if (
            canonical_document.get("source_system") != "confluence"
            or canonical_document.get("source_type") != "wiki_page"
            or not isinstance(title, str)
            or title != structure.page_title
        ):
            _fail(
                ConfluenceChunkingFailureCategory.DOCUMENT_STRUCTURE_IDENTITY_MISMATCH
            )
        try:
            self._schema_validator.validate_record(
                "CanonicalDocument",
                canonical_document,
            )
        except (FoundationValidationError, TypeError, ValueError):
            _fail(
                ConfluenceChunkingFailureCategory.CANONICAL_DOCUMENT_VALIDATION_FAILED
            )

    def _assemble_candidates(
        self,
        structure: WikiDocumentStructure,
        state: _MetricState,
    ) -> list[_Candidate]:
        views = self._section_views(structure.sections)
        candidates: list[_Candidate] = []
        index = 0
        while index < len(views):
            view = views[index]
            if view.is_empty:
                state.empty_sections_skipped += 1
                index += 1
                continue

            if self._merge_eligible(view):
                assert view.prose_only_body is not None
                body = view.prose_only_body
                absorbed_through = index
                while self._count_exact(
                    self._breadcrumb(view.section.heading_path), body
                ) < self._profile.minimum_tokens:
                    next_index = absorbed_through + 1
                    if next_index >= len(views):
                        break
                    next_view = views[next_index]
                    if not self._merge_pair_allowed(view, next_view):
                        break
                    assert next_view.prose_only_body is not None
                    heading = self._reconstructed_heading(next_view.section)
                    trial_body = TextNormalizationRules.normalize_text(
                        f"{body}\n\n{heading}\n\n{next_view.prose_only_body}"
                    )
                    trial_count = self._count_exact(
                        self._breadcrumb(view.section.heading_path),
                        trial_body,
                    )
                    if trial_count > self._profile.hard_maximum_tokens:
                        break
                    body = trial_body
                    absorbed_through = next_index
                    state.sections_merged += 1
                candidates.append(self._prose_candidate(view.section, body))
                index = absorbed_through + 1
                continue

            candidates.extend(self._section_candidates(view.section))
            index += 1
        return candidates

    def _section_views(
        self,
        sections: Sequence[WikiSection],
    ) -> list[_SectionView]:
        stack: list[tuple[int, int]] = []
        views: list[_SectionView] = []
        for section in sections:
            level = section.heading_level
            if level is None:
                parent_identity: object = _DOCUMENT_ROOT
            else:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent_identity = stack[-1][1] if stack else _DOCUMENT_ROOT
                stack.append((level, section.source_ordinal))

            prose_blocks = [
                block.text
                for block in section.blocks
                if isinstance(block, WikiProseBlock)
            ]
            has_structural_block = any(
                isinstance(block, (WikiTableBlock, WikiCodeBlock))
                for block in section.blocks
            )
            all_prose = bool(section.blocks) and len(prose_blocks) == len(
                section.blocks
            )
            joined_prose = TextNormalizationRules.normalize_text(
                "\n\n".join(prose_blocks)
            )
            prose_only_body = joined_prose if all_prose and joined_prose else None
            views.append(
                _SectionView(
                    section=section,
                    parent_identity=parent_identity,
                    prose_only_body=prose_only_body,
                    is_empty=(
                        level is not None
                        and not has_structural_block
                        and joined_prose == ""
                    ),
                )
            )
        return views

    @staticmethod
    def _merge_eligible(view: _SectionView) -> bool:
        return (
            view.section.heading_level in (2, 3)
            and view.prose_only_body is not None
        )

    def _merge_pair_allowed(
        self,
        first: _SectionView,
        second: _SectionView,
    ) -> bool:
        return (
            self._merge_eligible(second)
            and first.section.heading_level == second.section.heading_level
            and first.parent_identity == second.parent_identity
        )

    @staticmethod
    def _reconstructed_heading(section: WikiSection) -> str:
        level = section.heading_level
        if level not in (2, 3) or not section.heading_path:
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        return f"{'#' * level} {section.heading_path[-1]}"

    def _section_candidates(self, section: WikiSection) -> list[_Candidate]:
        breadcrumb = self._breadcrumb(section.heading_path)
        candidates: list[_Candidate] = []
        prose_buffer: list[str] = []
        table_ordinal = 0
        code_ordinal = 0

        def flush_prose() -> None:
            if not prose_buffer:
                return
            body = TextNormalizationRules.normalize_text(
                "\n\n".join(prose_buffer)
            )
            prose_buffer.clear()
            if body:
                candidates.append(self._prose_candidate(section, body))

        for block in section.blocks:
            if isinstance(block, WikiProseBlock):
                prose_buffer.append(block.text)
                continue
            flush_prose()
            if isinstance(block, WikiTableBlock):
                candidates.append(
                    _Candidate(
                        kind="table",
                        breadcrumb=breadcrumb,
                        heading_path=section.heading_path,
                        body=block.raw_text,
                        unit_key=f"{breadcrumb}#table{table_ordinal}",
                        table_block=block,
                    )
                )
                table_ordinal += 1
            elif isinstance(block, WikiCodeBlock):
                candidates.append(
                    _Candidate(
                        kind="code_block",
                        breadcrumb=breadcrumb,
                        heading_path=section.heading_path,
                        body=block.raw_text,
                        unit_key=f"{breadcrumb}#code{code_ordinal}",
                        code_block=block,
                    )
                )
                code_ordinal += 1
            else:  # pragma: no cover - frozen union guards this upstream
                _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        flush_prose()
        return candidates

    def _prose_candidate(self, section: WikiSection, body: str) -> _Candidate:
        breadcrumb = self._breadcrumb(section.heading_path)
        return _Candidate(
            kind="prose",
            breadcrumb=breadcrumb,
            heading_path=section.heading_path,
            body=body,
            unit_key=breadcrumb,
        )

    @staticmethod
    def _breadcrumb(heading_path: Sequence[str]) -> str:
        if not heading_path or not all(
            isinstance(entry, str) and entry != "" for entry in heading_path
        ):
            _fail(
                ConfluenceChunkingFailureCategory.DOCUMENT_STRUCTURE_IDENTITY_MISMATCH
            )
        return _BREADCRUMB_SEPARATOR.join(heading_path)

    def _split_candidate(
        self,
        candidate: _Candidate,
        state: _MetricState,
    ) -> list[_Part]:
        self._require_breadcrumb_capacity(candidate.breadcrumb)
        atomic_count = self._count_exact(candidate.breadcrumb, candidate.body)
        if atomic_count <= self._profile.hard_maximum_tokens:
            return [self._atomic_part(candidate)]

        state.oversize_splits += 1
        if candidate.kind == "prose":
            state.prose_split_units += 1
            bodies = self._split_prose(candidate, state)
        elif candidate.kind == "code_block":
            state.code_split_units += 1
            bodies = self._split_code(candidate)
        elif candidate.kind == "table":
            state.table_split_units += 1
            bodies = self._split_table(candidate)
        else:  # pragma: no cover - candidate construction is closed
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        if len(bodies) < 2:
            _fail(ConfluenceChunkingFailureCategory.CHUNK_BUDGET_VIOLATION)
        total = len(bodies)
        return [
            _Part(
                kind=candidate.kind,
                breadcrumb=candidate.breadcrumb,
                heading_path=candidate.heading_path,
                body=body,
                unit_key=self._split_unit_key(candidate, part_index),
                part_index=part_index,
                part_total=total,
            )
            for part_index, body in enumerate(bodies)
        ]

    @staticmethod
    def _atomic_part(candidate: _Candidate) -> _Part:
        return _Part(
            kind=candidate.kind,
            breadcrumb=candidate.breadcrumb,
            heading_path=candidate.heading_path,
            body=candidate.body,
            unit_key=candidate.unit_key,
        )

    @staticmethod
    def _split_unit_key(candidate: _Candidate, part_index: int) -> str:
        if candidate.kind == "prose":
            return f"{candidate.unit_key}#w{part_index}"
        if candidate.kind == "table":
            return f"{candidate.unit_key}#g{part_index}"
        return candidate.unit_key

    def _require_breadcrumb_capacity(self, breadcrumb: str) -> None:
        if self._count_text(TextNormalizationRules.normalize_text(breadcrumb)) >= (
            self._profile.hard_maximum_tokens
        ):
            _fail(ConfluenceChunkingFailureCategory.BREADCRUMB_OVER_HARD_MAX)

    def _split_prose(
        self,
        candidate: _Candidate,
        state: _MetricState,
    ) -> list[str]:
        units = self._refine_prose_range(
            body=candidate.body,
            breadcrumb=candidate.breadcrumb,
            start=0,
            end=len(candidate.body),
            boundary_level=0,
            state=state,
        )
        if not units:
            _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_PROSE_FRAGMENT)

        windows: list[str] = []
        cursor = 0
        previous_new_body = ""
        while cursor < len(units):
            first = units[cursor]
            first_new_body = candidate.body[first.start : first.end]
            overlap = ""
            if windows:
                overlap = self._select_overlap(
                    previous_body=previous_new_body,
                    breadcrumb=candidate.breadcrumb,
                    next_body=first_new_body,
                )

            best_end: int | None = None
            for end_index in range(cursor + 1, len(units) + 1):
                new_body = candidate.body[
                    units[cursor].start : units[end_index - 1].end
                ]
                if self._count_exact(
                    candidate.breadcrumb,
                    overlap + new_body,
                ) <= self._profile.target_tokens:
                    best_end = end_index
            if best_end is None:
                best_end = cursor + 1
                trial_count = self._count_exact(
                    candidate.breadcrumb,
                    overlap + first_new_body,
                )
                if trial_count > self._profile.hard_maximum_tokens and overlap:
                    overlap = ""
                    trial_count = self._count_exact(
                        candidate.breadcrumb,
                        first_new_body,
                    )
                if trial_count > self._profile.hard_maximum_tokens:
                    _fail(
                        ConfluenceChunkingFailureCategory.UNSPLITTABLE_PROSE_FRAGMENT
                    )

            new_body = candidate.body[
                units[cursor].start : units[best_end - 1].end
            ]
            body = overlap + new_body
            if self._count_exact(candidate.breadcrumb, body) > (
                self._profile.hard_maximum_tokens
            ):
                _fail(ConfluenceChunkingFailureCategory.CHUNK_BUDGET_VIOLATION)
            if overlap:
                state.overlap_windows += 1
            windows.append(body)
            previous_new_body = new_body
            cursor = best_end
        return windows

    def _refine_prose_range(
        self,
        *,
        body: str,
        breadcrumb: str,
        start: int,
        end: int,
        boundary_level: int,
        state: _MetricState,
    ) -> list[_SourceRange]:
        fragment = body[start:end]
        if self._count_exact(breadcrumb, fragment) <= (
            self._profile.hard_maximum_tokens
        ):
            return [_SourceRange(start, end)]

        if boundary_level < 3:
            boundaries = self._boundaries_for_level(fragment, boundary_level)
            if len(boundaries) > 1:
                ranges: list[_SourceRange] = []
                cursor = start
                for relative_end in boundaries:
                    absolute_end = start + relative_end
                    ranges.extend(
                        self._refine_prose_range(
                            body=body,
                            breadcrumb=breadcrumb,
                            start=cursor,
                            end=absolute_end,
                            boundary_level=boundary_level + 1,
                            state=state,
                        )
                    )
                    cursor = absolute_end
                return ranges
            return self._refine_prose_range(
                body=body,
                breadcrumb=breadcrumb,
                start=start,
                end=end,
                boundary_level=boundary_level + 1,
                state=state,
            )

        state.tokenizer_boundary_fallbacks += 1
        return self._token_offset_ranges(
            body=body,
            breadcrumb=breadcrumb,
            start=start,
            end=end,
        )

    @staticmethod
    def _boundaries_for_level(text: str, level: int) -> list[int]:
        if level == 0:
            candidates = [match.end() for match in _PARAGRAPH_BOUNDARY.finditer(text)]
        elif level == 1:
            candidates = [match.end() for match in _SENTENCE_BOUNDARY.finditer(text)]
        else:
            candidates = [index + 1 for index, char in enumerate(text) if char == "\n"]
        boundaries = sorted({value for value in candidates if 0 < value < len(text)})
        boundaries.append(len(text))
        return boundaries

    def _token_offset_ranges(
        self,
        *,
        body: str,
        breadcrumb: str,
        start: int,
        end: int,
    ) -> list[_SourceRange]:
        ranges: list[_SourceRange] = []
        cursor = start
        prefix_length = len(TextNormalizationRules.normalize_text(breadcrumb)) + 2
        while cursor < end:
            remaining = body[cursor:end]
            if self._count_exact(breadcrumb, remaining) <= (
                self._profile.hard_maximum_tokens
            ):
                ranges.append(_SourceRange(cursor, end))
                break
            exact = self._exact_text(breadcrumb, remaining)
            tokenization = self._tokenizer.tokenize(text=exact)
            relative_ends = sorted(
                {
                    span.end - prefix_length
                    for span in tokenization.spans
                    if 0 < span.end - prefix_length < len(remaining)
                }
            )
            best_target: int | None = None
            best_hard: int | None = None
            for relative_end in relative_ends:
                fragment = remaining[:relative_end]
                count = self._count_exact(breadcrumb, fragment)
                if count <= self._profile.hard_maximum_tokens:
                    best_hard = relative_end
                if count <= self._profile.target_tokens:
                    best_target = relative_end
            chosen = best_target if best_target is not None else best_hard
            if chosen is None or chosen <= 0:
                _fail(
                    ConfluenceChunkingFailureCategory.UNSPLITTABLE_PROSE_FRAGMENT
                )
            ranges.append(_SourceRange(cursor, cursor + chosen))
            cursor += chosen
        return ranges

    def _select_overlap(
        self,
        *,
        previous_body: str,
        breadcrumb: str,
        next_body: str,
    ) -> str:
        if not previous_body:
            return ""
        next_count = self._count_exact(breadcrumb, next_body)
        target_bound = (
            self._profile.target_tokens
            if next_count <= self._profile.target_tokens
            else self._profile.hard_maximum_tokens
        )
        candidate_groups = self._overlap_start_groups(previous_body)
        for starts in candidate_groups:
            valid: list[tuple[int, str]] = []
            for start in starts:
                suffix = previous_body[start:]
                normalized_suffix = TextNormalizationRules.normalize_text(suffix)
                if not normalized_suffix:
                    continue
                overlap_count = self._count_text(normalized_suffix)
                if overlap_count > self._profile.overlap_tokens:
                    continue
                final_count = self._count_exact(
                    breadcrumb,
                    suffix + next_body,
                )
                if final_count <= target_bound and final_count <= (
                    self._profile.hard_maximum_tokens
                ):
                    valid.append((start, suffix))
            if valid:
                return min(valid, key=lambda item: item[0])[1]
        return ""

    def _overlap_start_groups(self, text: str) -> list[list[int]]:
        paragraph = sorted(
            {0, *(match.end() for match in _PARAGRAPH_BOUNDARY.finditer(text))}
        )
        sentence = sorted(
            {0, *(match.end() for match in _SENTENCE_BOUNDARY.finditer(text))}
        )
        line = sorted({0, *(index + 1 for index, char in enumerate(text) if char == "\n")})
        normalized = TextNormalizationRules.normalize_text(text)
        token_starts = {0}
        if normalized:
            token_starts.update(
                span.start
                for span in self._tokenizer.tokenize(text=normalized).spans
                if 0 < span.start < len(text)
            )
        return [paragraph, sentence, line, sorted(token_starts)]

    def _split_code(self, candidate: _Candidate) -> list[str]:
        block = candidate.code_block
        if block is None:
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        lines = list(block.body_lines)
        if not lines:
            _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE)

        windows: list[str] = []
        cursor = 0
        previous_window: list[str] = []
        while cursor < len(lines):
            maximum_overlap = min(
                self._profile.code_window_overlap_lines,
                len(previous_window),
                self._profile.code_window_max_lines - 1,
            )
            overlap: list[str] = []
            for overlap_count in range(maximum_overlap, -1, -1):
                trial_overlap = (
                    previous_window[-overlap_count:] if overlap_count else []
                )
                first_trial = self._code_body(block, trial_overlap + [lines[cursor]])
                first_count = self._count_exact(candidate.breadcrumb, first_trial)
                no_overlap_count = self._count_exact(
                    candidate.breadcrumb,
                    self._code_body(block, [lines[cursor]]),
                )
                target = (
                    self._profile.code_window_target_tokens
                    if no_overlap_count <= self._profile.code_window_target_tokens
                    else self._profile.hard_maximum_tokens
                )
                if (
                    first_count <= self._profile.hard_maximum_tokens
                    and first_count <= target
                ):
                    overlap = trial_overlap
                    break
            else:
                _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE)

            available_new_lines = self._profile.code_window_max_lines - len(overlap)
            upper = min(len(lines), cursor + available_new_lines)
            best_end: int | None = None
            for end_index in range(cursor + 1, upper + 1):
                body = self._code_body(block, overlap + lines[cursor:end_index])
                if self._count_exact(candidate.breadcrumb, body) <= (
                    self._profile.code_window_target_tokens
                ):
                    best_end = end_index
            if best_end is None:
                best_end = cursor + 1
                body = self._code_body(block, overlap + [lines[cursor]])
                if self._count_exact(candidate.breadcrumb, body) > (
                    self._profile.hard_maximum_tokens
                ):
                    _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE)

            emitted_lines = overlap + lines[cursor:best_end]
            body = self._code_body(block, emitted_lines)
            if self._count_exact(candidate.breadcrumb, body) > (
                self._profile.hard_maximum_tokens
            ):
                _fail(ConfluenceChunkingFailureCategory.CHUNK_BUDGET_VIOLATION)
            windows.append(body)
            previous_window = emitted_lines
            cursor = best_end
        return windows

    @staticmethod
    def _code_body(block: WikiCodeBlock, lines: Sequence[str]) -> str:
        raw_lines = block.raw_text.split("\n")
        if len(raw_lines) < 2:
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        opening = raw_lines[0]
        closing = raw_lines[-1]
        if (
            block.fence_marker not in opening
            or block.fence_marker not in closing
        ):
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        return "\n".join([opening, *lines, closing])

    def _split_table(self, candidate: _Candidate) -> list[str]:
        block = candidate.table_block
        if block is None:
            _fail(ConfluenceChunkingFailureCategory.CHUNKING_FAILED)
        header_body = "\n".join([block.header_line, block.separator_line])
        if self._count_exact(candidate.breadcrumb, header_body) > (
            self._profile.hard_maximum_tokens
        ):
            _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_HEADER)
        if not block.row_lines:
            _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_HEADER)

        windows: list[str] = []
        cursor = 0
        while cursor < len(block.row_lines):
            one_row = self._table_body(block, block.row_lines[cursor : cursor + 1])
            if self._count_exact(candidate.breadcrumb, one_row) > (
                self._profile.hard_maximum_tokens
            ):
                _fail(ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_ROW)
            best_end: int | None = None
            for end_index in range(cursor + 1, len(block.row_lines) + 1):
                body = self._table_body(block, block.row_lines[cursor:end_index])
                if self._count_exact(candidate.breadcrumb, body) <= (
                    self._profile.target_tokens
                ):
                    best_end = end_index
            if best_end is None:
                best_end = cursor + 1
            body = self._table_body(block, block.row_lines[cursor:best_end])
            if self._count_exact(candidate.breadcrumb, body) > (
                self._profile.hard_maximum_tokens
            ):
                _fail(ConfluenceChunkingFailureCategory.CHUNK_BUDGET_VIOLATION)
            windows.append(body)
            cursor = best_end
        return windows

    @staticmethod
    def _table_body(block: WikiTableBlock, rows: Sequence[str]) -> str:
        return "\n".join([block.header_line, block.separator_line, *rows])

    def _build_records(
        self,
        *,
        canonical_document: Mapping[str, object],
        parts: Sequence[_Part],
    ) -> tuple[list[dict[str, object]], list[int]]:
        document_id = canonical_document["document_id"]
        if not isinstance(document_id, str):  # already schema-validated
            _fail(
                ConfluenceChunkingFailureCategory.CANONICAL_DOCUMENT_VALIDATION_FAILED
            )
        records: list[dict[str, object]] = []
        token_counts: list[int] = []
        seen_preimages: dict[str, tuple[str, str, str, str]] = {}
        duplicate_counts: dict[str, int] = {}

        for part in parts:
            text = self._exact_text(part.breadcrumb, part.body)
            token_count = self._count_text(text)
            if token_count > self._profile.hard_maximum_tokens:
                _fail(ConfluenceChunkingFailureCategory.CHUNK_BUDGET_VIOLATION)
            preimage = ("confluence", document_id, part.unit_key, text)
            base_id = self._chunk_id_generator.generate_chunk_id(*preimage)
            if base_id in seen_preimages:
                if seen_preimages[base_id] != preimage:
                    _fail(ConfluenceChunkingFailureCategory.CHUNK_ID_COLLISION)
                duplicate_counts[base_id] = duplicate_counts.get(base_id, 0) + 1
                chunk_id = f"{base_id}-{duplicate_counts[base_id]}"
            else:
                seen_preimages[base_id] = preimage
                duplicate_counts[base_id] = 0
                chunk_id = base_id

            try:
                record = self._chunk_record_builder.build(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source_system="confluence",
                    source_type="wiki_page",
                    text=text,
                    content_kind=part.kind,
                    language="unknown",
                    token_count=token_count,
                    acl_tags=["restricted:unresolved"],
                    chunker_version=self._profile.chunker_version,
                    title=canonical_document.get("title"),
                    heading_path=list(part.heading_path),
                    space_key=canonical_document.get("space_key"),
                    page_id=canonical_document.get("page_id"),
                    repo=None,
                    branch=None,
                    file_path=None,
                    symbol=None,
                    line_start=None,
                    line_end=None,
                    part_index=part.part_index,
                    part_total=part.part_total,
                    jira_keys=[],
                    relation_ids=[],
                    source_version=canonical_document.get("source_version"),
                    updated_at=canonical_document.get("updated_at"),
                )
                self._schema_validator.validate_record("ChunkRecord", record)
            except (FoundationValidationError, TypeError, ValueError):
                _fail(
                    ConfluenceChunkingFailureCategory.CHUNK_RECORD_VALIDATION_FAILED
                )
            records.append(record)
            token_counts.append(token_count)
        return records, token_counts

    @staticmethod
    def _metrics(
        records: Sequence[Mapping[str, object]],
        token_counts: Sequence[int],
        state: _MetricState,
    ) -> dict[str, object]:
        chunks_by_kind = {"code_block": 0, "prose": 0, "table": 0}
        for record in records:
            kind = record["content_kind"]
            if isinstance(kind, str) and kind in chunks_by_kind:
                chunks_by_kind[kind] += 1
        return {
            "chunks_total": len(records),
            "chunks_by_kind": chunks_by_kind,
            "chunks_over_hard_max": 0,
            "sections_merged": state.sections_merged,
            "oversize_splits": state.oversize_splits,
            "empty_sections_skipped": state.empty_sections_skipped,
            "token_count_p50": _nearest_rank(token_counts, 50),
            "token_count_p95": _nearest_rank(token_counts, 95),
            "prose_split_units": state.prose_split_units,
            "table_split_units": state.table_split_units,
            "code_split_units": state.code_split_units,
            "overlap_windows": state.overlap_windows,
            "tokenizer_boundary_fallbacks": state.tokenizer_boundary_fallbacks,
            "minimum_token_count": min(token_counts, default=0),
            "maximum_token_count": max(token_counts, default=0),
        }

    def _count_exact(self, breadcrumb: str, body: str) -> int:
        return self._count_text(self._exact_text(breadcrumb, body))

    def _count_text(self, text: str) -> int:
        return self._tokenizer.tokenize(text=text).token_count

    @staticmethod
    def _exact_text(breadcrumb: str, body: str) -> str:
        return TextNormalizationRules.normalize_text(
            f"{breadcrumb}\n\n{body}"
        )


def _nearest_rank(values: Sequence[int], p_percent: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = (p_percent * len(ordered) + 99) // 100
    return ordered[rank - 1]
