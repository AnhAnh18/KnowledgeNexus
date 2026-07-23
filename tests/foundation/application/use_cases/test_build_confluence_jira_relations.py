from __future__ import annotations

from copy import deepcopy

import pytest

from knowledgenexus.foundation.application.use_cases import (
    BuildConfluenceJiraRelations,
)
from knowledgenexus.foundation.domain.models import (
    ChunkingResult,
    ConfluenceJiraRelationError,
    ConfluenceJiraRelationFailureCategory,
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.records import (
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import (
    DocumentIdGenerator,
    RelationIdGenerator,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


CREATED_AT = "2026-07-22T00:00:00Z"
UPDATED_AT = "2026-07-20T01:02:03Z"
CRAWLED_AT = "2026-07-22T00:00:00Z"


def _profile() -> JiraRelationProfile:
    return JiraRelationProfile(
        schema_version=1,
        extraction_mode=JIRA_EXTRACTION_MODE,
        key_pattern=JIRA_KEY_PATTERN,
        allowed_project_keys=("SVMCSPEN",),
    )


def _canonical(body: str) -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:1000",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=body,
        acl_id="acl:confluence:page:1000",
        crawled_at=CRAWLED_AT,
        title="Fixture Foundation",
        space_key="SPACE",
        page_id="1000",
        source_version="9",
        jira_keys=[],
        relation_ids=[],
        updated_at=UPDATED_AT,
        metadata={"nested": ["preserved"]},
    )


def _chunk(index: int = 0) -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=f"chunk:confluence:{index:016x}",
        document_id="confluence:page:1000",
        source_system="confluence",
        source_type="wiki_page",
        text=f"Fixture Foundation\n\nchunk text {index}",
        content_kind="prose",
        language="unknown",
        token_count=7,
        acl_tags=["restricted:unresolved"],
        chunker_version="1.2.0",
        title="Fixture Foundation",
        heading_path=["Fixture Foundation"],
        space_key="SPACE",
        page_id="1000",
        jira_keys=[],
        relation_ids=[],
        source_version="9",
        updated_at=UPDATED_AT,
    )


def _chunking(*records: dict[str, object]) -> ChunkingResult:
    return ChunkingResult(
        records=tuple(records),
        metrics={
            "chunks_total": len(records),
            "chunks_over_hard_max": 0,
        },
    )


def _use_case(
    *, relation_id_generator: object = RelationIdGenerator,
    relation_record_builder: object = RelationRecordBuilder,
    schema_validator: object | None = None,
) -> BuildConfluenceJiraRelations:
    return BuildConfluenceJiraRelations(
        profile=_profile(),
        document_id_generator=DocumentIdGenerator,
        relation_id_generator=relation_id_generator,  # type: ignore[arg-type]
        relation_record_builder=relation_record_builder,  # type: ignore[arg-type]
        schema_validator=schema_validator or FoundationSchemaValidator(),  # type: ignore[arg-type]
    )


def _execute(
    body: str,
    *,
    canonical: dict[str, object] | None = None,
    chunks: ChunkingResult | None = None,
    created_at: str = CREATED_AT,
    use_case: BuildConfluenceJiraRelations | None = None,
):
    return (use_case or _use_case()).execute(
        normalized_body_text=body,
        canonical_document=canonical or _canonical(body),
        chunking_result=chunks or _chunking(_chunk(0), _chunk(1)),
        created_at=created_at,
    )


def test_extracts_allowlisted_relations_once_in_first_occurrence_order() -> None:
    body = (
        "SVMCSPEN-20 and SHA-256 then SVMCSPEN-3, "
        "SVMCSPEN-20 and ISO-8601."
    )

    result = _execute(body)

    assert result.quality_observation.unique_key_like_candidates == (
        "SVMCSPEN-20",
        "SHA-256",
        "SVMCSPEN-3",
        "ISO-8601",
    )
    assert result.quality_observation.allowlisted_keys == (
        "SVMCSPEN-20",
        "SVMCSPEN-3",
    )
    assert result.quality_observation.outside_allowlist_keys == (
        "SHA-256",
        "ISO-8601",
    )
    assert result.enriched_canonical_document["jira_keys"] == [
        "SVMCSPEN-20",
        "SVMCSPEN-3",
    ]
    assert [record["target_id"] for record in result.relations] == [
        "jira:issue:SVMCSPEN-20",
        "jira:issue:SVMCSPEN-3",
    ]
    assert result.metrics == {
        "candidate_occurrences": 5,
        "unique_key_like_count": 4,
        "allowlisted_unique_count": 2,
        "outside_allowlist_unique_count": 2,
        "duplicate_occurrences": 1,
        "relations_total": 2,
        "documents_enriched": 1,
        "chunks_enriched": 2,
    }


def test_relation_shape_id_and_page_level_propagation_are_exact() -> None:
    result = _execute("Decision tracked by SVMCSPEN-42.")
    relation = result.relations[0]
    expected_id = RelationIdGenerator.generate_relation_id(
        "confluence:page:1000",
        "mentions_jira_key",
        "jira:issue:SVMCSPEN-42",
    )

    assert relation == {
        "schema_version": "1.0",
        "relation_id": expected_id,
        "source_id": "confluence:page:1000",
        "target_id": "jira:issue:SVMCSPEN-42",
        "relation_type": "mentions_jira_key",
        "resolution_status": "unresolved_without_jira_api",
        "created_at": CREATED_AT,
        "evidence": "regex:page_body",
        "confidence": 0.95,
    }
    assert result.enriched_canonical_document["relation_ids"] == [expected_id]
    assert all(
        chunk["jira_keys"] == ["SVMCSPEN-42"]
        and chunk["relation_ids"] == [expected_id]
        for chunk in result.enriched_chunks
    )
    validator = FoundationSchemaValidator()
    validator.validate_record("RelationRecord", relation)
    validator.validate_record(
        "CanonicalDocument", result.enriched_canonical_document
    )
    for chunk in result.enriched_chunks:
        validator.validate_record("ChunkRecord", chunk)


def test_zero_relation_and_empty_body_are_valid() -> None:
    result = _execute("", chunks=_chunking())

    assert result.relations == ()
    assert result.enriched_canonical_document["jira_keys"] == []
    assert result.enriched_canonical_document["relation_ids"] == []
    assert result.enriched_chunks == ()
    assert result.metrics["relations_total"] == 0
    assert result.metrics["documents_enriched"] == 0
    assert result.metrics["chunks_enriched"] == 0


def test_scans_body_only_without_repairing_or_substring_matching() -> None:
    body = "svmcspen-1 xSVMCSPEN-2 SVMCSPEN-3x OUTSIDE-4"
    canonical = _canonical(body)
    canonical["title"] = "SVMCSPEN-99"
    chunk = _chunk()
    chunk["title"] = "SVMCSPEN-99"
    chunk["text"] = "SVMCSPEN-88"
    from knowledgenexus.foundation.domain.rules import ContentHasher

    chunk["content_hash"] = ContentHasher.hash_text("SVMCSPEN-88")

    result = _execute(body, canonical=canonical, chunks=_chunking(chunk))

    assert result.relations == ()
    assert result.quality_observation.unique_key_like_candidates == ("OUTSIDE-4",)


def test_inputs_are_not_mutated_and_non_link_fields_remain_exact() -> None:
    body = "SVMCSPEN-7"
    canonical = _canonical(body)
    chunks = _chunking(_chunk())
    canonical_before = deepcopy(canonical)
    chunks_before = deepcopy(chunks.records)

    result = _execute(body, canonical=canonical, chunks=chunks)

    assert canonical == canonical_before
    assert chunks.records == chunks_before
    enriched_canonical = deepcopy(result.enriched_canonical_document)
    enriched_canonical["jira_keys"] = []
    enriched_canonical["relation_ids"] = []
    assert enriched_canonical == canonical_before
    enriched_chunk = deepcopy(result.enriched_chunks[0])
    enriched_chunk["jira_keys"] = []
    enriched_chunk["relation_ids"] = []
    assert enriched_chunk == chunks_before[0]


@pytest.mark.parametrize(
    "created_at",
    ["", "not-a-date", "2026-07-22", "2026-13-40T25:61:61Z"],
)
def test_created_at_is_validated_even_when_no_relations(created_at: str) -> None:
    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute("", chunks=_chunking(), created_at=created_at)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.INVALID_CREATED_AT
    )


@pytest.mark.parametrize("body", ["e\u0301", "line  \n", "a\r\nb"])
def test_noncanonical_body_is_rejected(body: str) -> None:
    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.INVALID_NORMALIZED_BODY
    )


def test_body_must_match_canonical_content_hash() -> None:
    canonical = _canonical("body without a relation")

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute("SVMCSPEN-123", canonical=canonical)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.NORMALIZED_BODY_CONTENT_HASH_MISMATCH
    )


@pytest.mark.parametrize("field", ["jira_keys", "relation_ids"])
def test_dirty_canonical_linkage_is_rejected(field: str) -> None:
    body = "SVMCSPEN-1"
    canonical = _canonical(body)
    canonical[field] = (
        ["SVMCSPEN-999"]
        if field == "jira_keys"
        else ["rel:0000000000000000"]
    )

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, canonical=canonical)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.RELATION_STAGE_INPUT_NOT_PRISTINE
    )


@pytest.mark.parametrize("field", ["jira_keys", "relation_ids"])
def test_dirty_chunk_linkage_is_rejected(field: str) -> None:
    body = "SVMCSPEN-1"
    chunk = _chunk()
    chunk[field] = (
        ["SVMCSPEN-999"]
        if field == "jira_keys"
        else ["rel:0000000000000000"]
    )

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, chunks=_chunking(chunk))

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.RELATION_STAGE_INPUT_NOT_PRISTINE
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "confluence:page:2000"),
        ("source_version", "10"),
        ("source_system", "git"),
        ("source_type", "code_file"),
        ("page_id", "2000"),
        ("space_key", "OTHER"),
        ("title", "Other"),
        ("updated_at", "2026-07-21T00:00:00Z"),
    ],
)
def test_chunk_provenance_must_match_canonical(field: str, value: object) -> None:
    body = "SVMCSPEN-1"
    chunk = _chunk()
    chunk[field] = value

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, chunks=_chunking(chunk))

    assert exc_info.value.category in {
        ConfluenceJiraRelationFailureCategory.CHUNK_RECORD_INVALID,
        ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    }


def test_canonical_document_id_must_match_page_id() -> None:
    body = "SVMCSPEN-1"
    canonical = _canonical(body)
    canonical["document_id"] = "confluence:page:2000"

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, canonical=canonical)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.CANONICAL_DOCUMENT_INVALID
    )


def test_duplicate_chunk_ids_are_rejected() -> None:
    body = "SVMCSPEN-1"

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, chunks=_chunking(_chunk(), _chunk()))

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
    )


def test_chunk_text_hash_mismatch_is_rejected() -> None:
    body = "SVMCSPEN-1"
    chunk = _chunk()
    chunk["text"] = "changed without rehash"

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, chunks=_chunking(chunk))

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
    )


def test_chunk_count_metric_must_match_records() -> None:
    body = "SVMCSPEN-1"
    chunking = ChunkingResult(
        records=(_chunk(),),
        metrics={"chunks_total": 2, "chunks_over_hard_max": 0},
    )

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute(body, chunks=chunking)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.CANONICAL_CHUNK_IDENTITY_MISMATCH
    )


class _CollidingRelationIdGenerator:
    @staticmethod
    def generate_relation_id(*args: object) -> str:
        return "rel:0000000000000000"


def test_true_relation_id_collision_fails_without_suffix() -> None:
    use_case = _use_case(relation_id_generator=_CollidingRelationIdGenerator)

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute("SVMCSPEN-1 SVMCSPEN-2", use_case=use_case)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.RELATION_ID_COLLISION
    )


class _InvalidRelationBuilder:
    @staticmethod
    def build(**fields: object) -> dict[str, object]:
        return {"sensitive": "SVMCSPEN-SECRET"}


def test_relation_validation_failure_is_sanitized() -> None:
    use_case = _use_case(relation_record_builder=_InvalidRelationBuilder)

    with pytest.raises(ConfluenceJiraRelationError) as exc_info:
        _execute("SVMCSPEN-1", use_case=use_case)

    assert exc_info.value.category == (
        ConfluenceJiraRelationFailureCategory.RELATION_RECORD_VALIDATION_FAILED
    )
    assert "SVMCSPEN" not in str(exc_info.value)
    assert "1000" not in str(exc_info.value)


def test_deterministic_repeat_is_exact() -> None:
    body = "SVMCSPEN-9 SHA-256 SVMCSPEN-9"

    first = _execute(body)
    second = _execute(body)

    assert first == second
