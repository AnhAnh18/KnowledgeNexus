from __future__ import annotations

import re
from dataclasses import replace

import pytest

from knowledgenexus.foundation.application.use_cases.build_confluence_chunks import (
    BuildConfluenceChunks,
    _nearest_rank,
)
from knowledgenexus.foundation.domain.models import (
    CharacterSpan,
    ChunkingProfile,
    ConfluenceChunkingError,
    ConfluenceChunkingFailureCategory,
    TokenizerAsset,
    TokenizationResult,
    WikiCodeBlock,
    WikiDocumentStructure,
    WikiProseBlock,
    WikiSection,
    WikiTableBlock,
)
from knowledgenexus.foundation.domain.records import (
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import ChunkIdGenerator, ContentHasher
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParser,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class _CharacterTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(CharacterSpan(index, index + 1) for index in range(len(text)))
        )


class _WordTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(
                CharacterSpan(match.start(), match.end())
                for match in re.finditer(r"\S+", text)
            )
        )


class _FixedIdGenerator:
    @staticmethod
    def generate_chunk_id(*args: str) -> str:
        return "chunk:confluence:0123456789abcdef"


class _RecordingIdGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def generate_chunk_id(
        self,
        source_system: str,
        document_stable_key: str,
        unit_key: str,
        normalized_text: str,
    ) -> str:
        self.calls.append(
            (source_system, document_stable_key, unit_key, normalized_text)
        )
        return ChunkIdGenerator.generate_chunk_id(
            source_system,
            document_stable_key,
            unit_key,
            normalized_text,
        )


class _IndivisibleTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        if text == "":
            return TokenizationResult(spans=())
        count = 100 if len(text) > 20 else 1
        return TokenizationResult(
            spans=tuple(CharacterSpan(0, len(text)) for _ in range(count))
        )


def _profile(
    *,
    minimum: int = 5,
    target: int = 30,
    hard: int = 45,
    overlap: int = 8,
    code_target: int = 30,
    max_lines: int = 4,
    overlap_lines: int = 1,
):
    base = ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=96,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository="https://huggingface.co/BAAI/bge-m3",
        tokenizer_revision="5617a9f61b028005a4858fdac845db406aefb181",
        observed_license="MIT",
        provenance_url=(
            "https://huggingface.co/BAAI/bge-m3/tree/"
            "5617a9f61b028005a4858fdac845db406aefb181"
        ),
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17098108,
                sha256=(
                    "21106b6d7dab2952c1d496fb21d5dc9d"
                    "b75c28ed361a05f5020bbba27810dd08"
                ),
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )
    return replace(
        base,
        minimum_tokens=minimum,
        target_tokens=target,
        hard_maximum_tokens=hard,
        overlap_tokens=overlap,
        code_window_target_tokens=code_target,
        code_window_max_lines=max_lines,
        code_window_overlap_lines=overlap_lines,
    )


def _canonical(*, title: object = "Doc", body: str = "body") -> dict[str, object]:
    record = CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:1000",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=body,
        acl_id="acl:confluence:page:1000",
        crawled_at="2026-07-22T00:00:00Z",
        title="Doc",
        space_key="SPACE",
        page_id="1000",
        source_version="7",
        jira_keys=[],
        relation_ids=[],
        updated_at="2026-07-21T00:00:00Z",
        metadata={},
    )
    record["title"] = title
    return record


def _structure(body: str, *, title: str = "Doc") -> WikiDocumentStructure:
    return WikiStructureParser.parse(
        page_title=title,
        normalized_body_text=body,
    )


def _use_case(
    *,
    tokenizer: object | None = None,
    profile=None,
    id_generator: object = ChunkIdGenerator,
) -> BuildConfluenceChunks:
    return BuildConfluenceChunks(
        profile=profile or _profile(),
        tokenizer=tokenizer or _WordTokenizer(),
        chunk_id_generator=id_generator,
        chunk_record_builder=ChunkRecordBuilder,
        schema_validator=FoundationSchemaValidator(),
    )


def _execute(
    body: str,
    *,
    tokenizer: object | None = None,
    profile=None,
    structure: WikiDocumentStructure | None = None,
    canonical: dict[str, object] | None = None,
    id_generator: object = ChunkIdGenerator,
):
    return _use_case(
        tokenizer=tokenizer,
        profile=profile,
        id_generator=id_generator,
    ).execute(
        canonical_document=canonical or _canonical(body=body),
        structure=structure or _structure(body),
    )


def _body(record: dict[str, object]) -> str:
    return str(record["text"]).split("\n\n", 1)[1]


def test_atomic_prose_maps_exact_schema_fields_and_omits_wiki_nulls() -> None:
    result = _execute("## Overview\n\nFoundation text.")

    assert len(result.records) == 1
    record = result.records[0]
    assert record["schema_version"] == "1.0"
    assert record["document_id"] == "confluence:page:1000"
    assert record["source_system"] == "confluence"
    assert record["source_type"] == "wiki_page"
    assert record["content_kind"] == "prose"
    assert record["language"] == "unknown"
    assert record["text"] == "Doc › Overview\n\nFoundation text."
    assert record["heading_path"] == ["Doc", "Overview"]
    assert record["space_key"] == "SPACE"
    assert record["page_id"] == "1000"
    assert record["source_version"] == "7"
    assert record["updated_at"] == "2026-07-21T00:00:00Z"
    assert record["acl_tags"] == ["restricted:unresolved"]
    assert record["jira_keys"] == []
    assert record["relation_ids"] == []
    assert record["chunker_version"] == "1.2.0"
    assert record["content_hash"] == ContentHasher.hash_text(str(record["text"]))
    for absent in (
        "repo",
        "branch",
        "file_path",
        "symbol",
        "line_start",
        "line_end",
        "part_index",
        "part_total",
        "chunk_index",
        "total_chunks",
    ):
        assert absent not in record


def test_final_normalization_precedes_token_count_hash_and_id() -> None:
    section = WikiSection(
        heading_path=("Doc", "S"),
        heading_level=2,
        heading_source_line=1,
        source_ordinal=0,
        blocks=(WikiProseBlock("line   \r\n\r\n\r\nnext", 1),),
    )
    result = _execute(
        "unused",
        tokenizer=_CharacterTokenizer(),
        profile=_profile(hard=100, target=80, code_target=80),
        structure=WikiDocumentStructure("Doc", (section,)),
    )
    record = result.records[0]

    assert record["text"] == "Doc › S\n\nline\n\nnext"
    assert record["token_count"] == len(str(record["text"]))
    assert record["content_hash"] == ContentHasher.hash_text(str(record["text"]))


def test_canonical_document_id_is_the_id_generator_stable_key() -> None:
    generator = _RecordingIdGenerator()
    result = _execute("## S\n\nbody", id_generator=generator)

    assert len(result.records) == 1
    assert generator.calls[0][0] == "confluence"
    assert generator.calls[0][1] == result.records[0]["document_id"]
    assert generator.calls[0][1] == "confluence:page:1000"
    assert generator.calls[0][2] == "Doc › S"
    assert generator.calls[0][3] == result.records[0]["text"]


def test_prose_table_code_prose_stay_isolated_and_source_ordered() -> None:
    body = (
        "## Mixed\n\nlead\n\n"
        "| H |\n| --- |\n| V |\n\n"
        "```py\nprint(1)\n```\n\n"
        "tail"
    )
    result = _execute(body)

    assert [record["content_kind"] for record in result.records] == [
        "prose",
        "table",
        "code_block",
        "prose",
    ]
    assert [_body(record) for record in result.records] == [
        "lead",
        "| H |\n| --- |\n| V |",
        "```py\nprint(1)\n```",
        "tail",
    ]


def test_explicit_empty_section_only_increments_empty_metric() -> None:
    result = _execute("## Empty\n\n## Full\n\nbody")

    assert len(result.records) == 1
    assert result.metrics["empty_sections_skipped"] == 1


def test_root_level_h2_siblings_merge_and_reconstruct_absorbed_heading() -> None:
    profile = _profile(minimum=9, target=30, hard=45)
    result = _execute(
        "## A\n\none\n\n## B\n\ntwo three four five six",
        profile=profile,
    )

    assert len(result.records) == 1
    assert result.metrics["sections_merged"] == 1
    assert _body(result.records[0]) == "one\n\n## B\n\ntwo three four five six"
    assert result.records[0]["heading_path"] == ["Doc", "A"]


def test_skipped_level_root_h3_siblings_can_merge() -> None:
    result = _execute(
        "### A\n\none\n\n### B\n\ntwo three four five six",
        profile=_profile(minimum=9, target=30, hard=45),
    )

    assert result.metrics["sections_merged"] == 1
    assert "### B" in _body(result.records[0])


@pytest.mark.parametrize(
    "body",
    [
        "# A\n\none\n\n# B\n\ntwo three four five six",
        "## A\n\none\n\n### Child\n\nchild\n\n## B\n\ntwo three four five",
        "# Parent\n\n### Child\n\none\n\n## Peer\n\ntwo three four five",
    ],
)
def test_h1_or_intervening_section_does_not_merge(body: str) -> None:
    result = _execute(body, profile=_profile(minimum=20, target=30, hard=45))

    assert result.metrics["sections_merged"] == 0


def test_same_level_sections_with_different_parent_ordinals_do_not_merge() -> None:
    body = (
        "# Parent A\n\n## Shared\n\none\n\n"
        "# Parent B\n\n## Shared\n\ntwo three four five"
    )
    result = _execute(body, profile=_profile(minimum=20, target=30, hard=45))

    assert result.metrics["sections_merged"] == 0


def test_section_with_table_is_conservatively_not_mergeable() -> None:
    body = (
        "## A\n\none\n\n| H |\n| --- |\n| V |\n\n"
        "## B\n\ntwo three four five"
    )
    result = _execute(body, profile=_profile(minimum=20, target=30, hard=45))

    assert result.metrics["sections_merged"] == 0


def test_oversize_prose_splits_only_above_hard_max_and_parts_are_bounded() -> None:
    body = "## Long\n\n" + "a" * 20 + "\n\n" + "b" * 20
    profile = _profile(minimum=5, target=25, hard=30, overlap=5, code_target=25)
    result = _execute(body, tokenizer=_CharacterTokenizer(), profile=profile)

    assert len(result.records) >= 2
    assert result.metrics["oversize_splits"] == 1
    assert result.metrics["prose_split_units"] == 1
    assert all(record["part_total"] == len(result.records) for record in result.records)
    assert [record["part_index"] for record in result.records] == list(
        range(len(result.records))
    )
    assert all(record["token_count"] <= profile.hard_maximum_tokens for record in result.records)
    assert result.metrics["chunks_over_hard_max"] == 0


def test_forced_prose_overlap_is_nonzero_and_within_the_configured_upper_bound() -> None:
    source = "a" * 18 + "\n\n" + "b" * 18
    profile = _profile(minimum=2, target=30, hard=35, overlap=5, code_target=30)
    result = _execute(
        f"## S\n\n{source}",
        tokenizer=_CharacterTokenizer(),
        profile=profile,
    )

    assert len(result.records) == 2
    assert result.metrics["overlap_windows"] == 1
    second_body = _body(result.records[1])
    overlap = second_body.split("\n\n", 1)[0]
    assert overlap
    assert len(overlap) <= profile.overlap_tokens
    assert second_body.endswith("b" * 18)


def test_sentence_line_and_token_offset_fallbacks_make_progress() -> None:
    profile = _profile(minimum=2, target=22, hard=28, overlap=4, code_target=22)
    boundary_results = []
    for prose in (
        "Sentence one. Sentence two! Sentence three?",
        "line-one\nline-two\nline-three\nline-four",
    ):
        result = _execute(
            f"## S\n\n{prose}",
            tokenizer=_CharacterTokenizer(),
            profile=profile,
        )
        boundary_results.append(result)
        assert len(result.records) >= 2
        assert all(record["token_count"] <= profile.hard_maximum_tokens for record in result.records)
    assert all(
        result.metrics["tokenizer_boundary_fallbacks"] == 0
        for result in boundary_results
    )
    token_result = _execute(
        "## S\n\n" + "x" * 70,
        tokenizer=_CharacterTokenizer(),
        profile=profile,
    )
    assert token_result.metrics["tokenizer_boundary_fallbacks"] == 1


def test_indivisible_tokenizer_fragment_fails_closed_without_character_cutting() -> None:
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            "## S\n\n" + "x" * 70,
            tokenizer=_IndivisibleTokenizer(),
            profile=_profile(
                minimum=2,
                target=20,
                hard=30,
                overlap=4,
                code_target=20,
            ),
        )

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.UNSPLITTABLE_PROSE_FRAGMENT
    )


def test_unsplit_candidate_between_target_and_hard_is_not_split() -> None:
    profile = _profile(minimum=2, target=15, hard=40, overlap=4, code_target=15)
    result = _execute(
        "## S\n\n" + "x" * 20,
        tokenizer=_CharacterTokenizer(),
        profile=profile,
    )

    assert len(result.records) == 1
    assert "part_index" not in result.records[0]


def test_overlong_breadcrumb_fails_with_sanitized_category() -> None:
    structure = _structure("## " + "H" * 50 + "\n\nbody")
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            "unused",
            tokenizer=_CharacterTokenizer(),
            profile=_profile(target=20, hard=30, overlap=4, code_target=20),
            structure=structure,
        )

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.BREADCRUMB_OVER_HARD_MAX
    )
    assert "H" not in str(captured.value)


def test_code_windows_repeat_valid_fences_and_complete_lines() -> None:
    body = "## Code\n\n```py\n11111111\n22222222\n33333333\n44444444\n```"
    profile = _profile(
        minimum=2,
        target=32,
        hard=38,
        overlap=5,
        code_target=32,
        max_lines=2,
        overlap_lines=1,
    )
    result = _execute(body, tokenizer=_CharacterTokenizer(), profile=profile)

    assert len(result.records) >= 2
    assert result.metrics["code_split_units"] == 1
    for record in result.records:
        emitted = _body(record)
        assert emitted.startswith("```py\n")
        assert emitted.endswith("\n```")
        assert record["content_kind"] == "code_block"
        assert record["token_count"] <= profile.hard_maximum_tokens


def test_split_indented_code_repeats_exact_source_wrappers() -> None:
    body = (
        "## Code\n\n- list\n\n"
        "  ````py\n  11111111\n  22222222\n  33333333\n  `````"
    )
    profile = _profile(
        minimum=2,
        target=35,
        hard=42,
        overlap=5,
        code_target=35,
        max_lines=2,
        overlap_lines=1,
    )
    result = _execute(body, tokenizer=_CharacterTokenizer(), profile=profile)
    code_records = [
        record for record in result.records if record["content_kind"] == "code_block"
    ]

    assert len(code_records) >= 2
    for record in code_records:
        emitted = _body(record)
        assert emitted.startswith("  ````py\n")
        assert emitted.endswith("\n  `````")


def test_single_unsplittable_code_line_fails_without_disclosure() -> None:
    body = "## Code\n\n```\n" + "SECRET" * 20 + "\n```"
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            body,
            tokenizer=_CharacterTokenizer(),
            profile=_profile(target=25, hard=35, overlap=4, code_target=25),
        )

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.UNSPLITTABLE_CODE_LINE
    )
    assert "SECRET" not in str(captured.value)


def test_table_row_groups_repeat_header_without_row_overlap() -> None:
    body = (
        "## Table\n\n| H |\n| --- |\n"
        "| 11111111 |\n| 22222222 |\n| 33333333 |"
    )
    profile = _profile(minimum=2, target=40, hard=48, overlap=4, code_target=40)
    result = _execute(body, tokenizer=_CharacterTokenizer(), profile=profile)

    assert len(result.records) >= 2
    assert result.metrics["table_split_units"] == 1
    emitted_rows: list[str] = []
    for record in result.records:
        lines = _body(record).splitlines()
        assert lines[:2] == ["| H |", "| --- |"]
        emitted_rows.extend(lines[2:])
    assert emitted_rows == ["| 11111111 |", "| 22222222 |", "| 33333333 |"]


def test_unsplittable_table_header_fails_closed() -> None:
    body = "## Table\n\n| " + "H" * 30 + " |\n| " + "-" * 30 + " |\n| V |"
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            body,
            tokenizer=_CharacterTokenizer(),
            profile=_profile(target=30, hard=40, overlap=4, code_target=30),
        )

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_HEADER
    )


def test_unsplittable_table_row_fails_closed() -> None:
    body = "## Table\n\n| H |\n| --- |\n| " + "SECRET" * 20 + " |"
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            body,
            tokenizer=_CharacterTokenizer(),
            profile=_profile(target=25, hard=35, overlap=4, code_target=25),
        )

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.UNSPLITTABLE_TABLE_ROW
    )
    assert "SECRET" not in str(captured.value)


def test_exact_duplicate_preimage_receives_stable_suffix() -> None:
    table = WikiTableBlock("| H |\n| --- |", "| H |", "| --- |", (), 1, 2)
    section = WikiSection(
        ("Doc", "S"),
        2,
        1,
        0,
        (
            WikiProseBlock("same", 1),
            table,
            WikiProseBlock("same", 3),
        ),
    )
    result = _execute(
        "unused",
        structure=WikiDocumentStructure("Doc", (section,)),
        profile=_profile(hard=60, target=50, code_target=50),
    )

    assert str(result.records[2]["chunk_id"]).endswith("-1")
    assert not str(result.records[0]["chunk_id"]).endswith("-1")


def test_same_base_id_with_different_preimage_fails_as_collision() -> None:
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute(
            "## A\n\none\n\n## B\n\ntwo",
            id_generator=_FixedIdGenerator,
            profile=_profile(minimum=1),
        )

    assert captured.value.category is ConfluenceChunkingFailureCategory.CHUNK_ID_COLLISION


def test_split_unit_key_grammar_uses_part_suffixes_only_where_specified() -> None:
    prose_generator = _RecordingIdGenerator()
    prose = _execute(
        "## S\n\n" + "x" * 70,
        tokenizer=_CharacterTokenizer(),
        profile=_profile(minimum=2, target=20, hard=28, overlap=4, code_target=20),
        id_generator=prose_generator,
    )
    assert [call[2] for call in prose_generator.calls] == [
        f"Doc › S#w{index}" for index in range(len(prose.records))
    ]

    code_generator = _RecordingIdGenerator()
    code = _execute(
        "## S\n\n```\n11111111\n22222222\n33333333\n```",
        tokenizer=_CharacterTokenizer(),
        profile=_profile(
            minimum=2,
            target=25,
            hard=32,
            overlap=4,
            code_target=25,
            max_lines=2,
            overlap_lines=1,
        ),
        id_generator=code_generator,
    )
    assert len(code.records) >= 2
    assert {call[2] for call in code_generator.calls} == {"Doc › S#code0"}


@pytest.mark.parametrize("bad_title", [None, 7, "Other"])
def test_null_non_string_or_mismatched_title_fails_identity(bad_title: object) -> None:
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute("body", canonical=_canonical(title=bad_title))

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.DOCUMENT_STRUCTURE_IDENTITY_MISMATCH
    )


def test_invalid_canonical_document_fails_schema_validation_without_details() -> None:
    invalid = _canonical()
    invalid["crawled_at"] = "not-a-date"
    with pytest.raises(ConfluenceChunkingError) as captured:
        _execute("body", canonical=invalid)

    assert captured.value.category is (
        ConfluenceChunkingFailureCategory.CANONICAL_DOCUMENT_VALIDATION_FAILED
    )
    assert "not-a-date" not in str(captured.value)


def test_alternate_medium_identity_budget_changes_chunking() -> None:
    body = "## S\n\n" + "x" * 70
    smaller = _profile(minimum=2, target=20, hard=28, overlap=4, code_target=20)
    larger = _profile(minimum=2, target=45, hard=60, overlap=4, code_target=45)

    small_result = _execute(body, tokenizer=_CharacterTokenizer(), profile=smaller)
    large_result = _execute(body, tokenizer=_CharacterTokenizer(), profile=larger)

    assert smaller.active_profile == larger.active_profile == "medium"
    assert smaller.tokenizer_assets == larger.tokenizer_assets
    assert len(small_result.records) > len(large_result.records)


def test_nearest_rank_metrics_are_integer_deterministic_and_empty_safe() -> None:
    assert _nearest_rank([], 50) == 0
    assert _nearest_rank([40, 10, 30, 20], 50) == 20
    assert _nearest_rank([40, 10, 30, 20], 95) == 40


def test_same_input_returns_exact_ordered_records_and_metrics() -> None:
    body = "## A\n\none\n\n## B\n\ntwo"
    use_case = _use_case(profile=_profile(minimum=1))
    canonical = _canonical(body=body)
    structure = _structure(body)

    first = use_case.execute(canonical_document=canonical, structure=structure)
    second = use_case.execute(canonical_document=canonical, structure=structure)

    assert first.records == second.records
    assert first.metrics == second.metrics
