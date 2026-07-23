from __future__ import annotations

from copy import deepcopy

import pytest

from knowledgenexus.foundation.application.use_cases import (
    BuildConfluenceJiraRelations,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    ChunkingResult,
    ConfluenceJiraRelationResult,
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JiraRelationProfile,
    JiraRelationQualityObservation,
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
from knowledgenexus.foundation.domain.rules.acl_relation_input_validator import (
    AclRelationInputValidator,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)

CREATED_AT = "2026-07-22T00:00:00Z"
UPDATED_AT = "2026-07-20T01:02:03Z"
CRAWLED_AT = "2026-07-22T00:00:00Z"
BODY = "SVMCSPEN-20 and SHA-256 then SVMCSPEN-3, SVMCSPEN-20 and ISO-8601."

_Category = AclMaterializationFailureCategory
_DELETE = object()


def _profile() -> JiraRelationProfile:
    return JiraRelationProfile(
        schema_version=1,
        extraction_mode=JIRA_EXTRACTION_MODE,
        key_pattern=JIRA_KEY_PATTERN,
        allowed_project_keys=("SVMCSPEN",),
    )


def _canonical() -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:1000",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=BODY,
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


def _chunk(index: int) -> dict[str, object]:
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


def _valid_result(*, chunk_count: int = 2) -> ConfluenceJiraRelationResult:
    use_case = BuildConfluenceJiraRelations(
        profile=_profile(),
        document_id_generator=DocumentIdGenerator,
        relation_id_generator=RelationIdGenerator,
        relation_record_builder=RelationRecordBuilder,
        schema_validator=FoundationSchemaValidator(),
    )
    chunks = ChunkingResult(
        records=tuple(_chunk(i) for i in range(chunk_count)),
        metrics={"chunks_total": chunk_count, "chunks_over_hard_max": 0},
    )
    return use_case.execute(
        normalized_body_text=BODY,
        canonical_document=_canonical(),
        chunking_result=chunks,
        created_at=CREATED_AT,
    )


def _validator() -> AclRelationInputValidator:
    return AclRelationInputValidator(schema_validator=FoundationSchemaValidator())


def _rebuild(
    result: ConfluenceJiraRelationResult,
    *,
    canonical=None,
    chunks=None,
    relations=None,
    quality=None,
    metrics=None,
) -> ConfluenceJiraRelationResult:
    return ConfluenceJiraRelationResult(
        enriched_canonical_document=(
            canonical
            if canonical is not None
            else deepcopy(result.enriched_canonical_document)
        ),
        enriched_chunks=(
            chunks if chunks is not None else deepcopy(result.enriched_chunks)
        ),
        relations=(
            relations if relations is not None else deepcopy(result.relations)
        ),
        quality_observation=(
            quality if quality is not None else result.quality_observation
        ),
        metrics=metrics if metrics is not None else deepcopy(result.metrics),
    )


def _apply(mapping: dict[str, object], changes: dict[str, object]) -> None:
    for key, value in changes.items():
        if value is _DELETE:
            mapping.pop(key, None)
        else:
            mapping[key] = value


def _mutate_canonical(result, **changes) -> ConfluenceJiraRelationResult:
    canonical = deepcopy(result.enriched_canonical_document)
    _apply(canonical, changes)
    return _rebuild(result, canonical=canonical)


def _mutate_chunk(result, index=0, **changes) -> ConfluenceJiraRelationResult:
    chunks = [dict(chunk) for chunk in deepcopy(result.enriched_chunks)]
    _apply(chunks[index], changes)
    return _rebuild(result, chunks=tuple(chunks))


def _mutate_relation(result, index=0, **changes) -> ConfluenceJiraRelationResult:
    relations = [dict(record) for record in deepcopy(result.relations)]
    _apply(relations[index], changes)
    return _rebuild(result, relations=tuple(relations))


def _mutate_quality(result, *, unique=None, allow=None, outside=None):
    quality = result.quality_observation
    return _rebuild(
        result,
        quality=JiraRelationQualityObservation(
            unique_key_like_candidates=(
                unique
                if unique is not None
                else quality.unique_key_like_candidates
            ),
            allowlisted_keys=(
                allow if allow is not None else quality.allowlisted_keys
            ),
            outside_allowlist_keys=(
                outside if outside is not None else quality.outside_allowlist_keys
            ),
        ),
    )


def _mutate_metrics(result, **changes) -> ConfluenceJiraRelationResult:
    metrics = deepcopy(result.metrics)
    _apply(metrics, changes)
    return _rebuild(result, metrics=metrics)


def _reject(result, category: _Category) -> AclMaterializationError:
    with pytest.raises(AclMaterializationError) as exc:
        _validator().validate(result)
    assert exc.value.category is category
    return exc.value


# --- M6E actual model bindings ------------------------------------------------


def test_valid_m6e_result_is_accepted() -> None:
    _validator().validate(_valid_result())


def test_validator_consumes_the_real_m6e_result_fields() -> None:
    result = _valid_result()
    # The real result exposes these exact fields, not a parallel DTO.
    assert result.enriched_canonical_document["jira_keys"] == [
        "SVMCSPEN-20",
        "SVMCSPEN-3",
    ]
    assert result.enriched_chunks[0]["jira_keys"] == ["SVMCSPEN-20", "SVMCSPEN-3"]
    assert result.quality_observation.unique_key_like_candidates == (
        "SVMCSPEN-20",
        "SHA-256",
        "SVMCSPEN-3",
        "ISO-8601",
    )
    _validator().validate(result)


def test_validate_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        _validator().validate({"enriched_canonical_document": {}})  # type: ignore[arg-type]


def test_inputs_are_not_modified_by_validation() -> None:
    result = _valid_result()
    before_doc = deepcopy(result.enriched_canonical_document)
    before_chunks = deepcopy(result.enriched_chunks)
    before_relations = deepcopy(result.relations)

    _validator().validate(result)

    assert result.enriched_canonical_document == before_doc
    assert result.enriched_chunks == before_chunks
    assert result.relations == before_relations


# --- Canonical provenance -----------------------------------------------------


def test_wrong_document_id_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), document_id="confluence:page:2000"),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_wrong_acl_id_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), acl_id="acl:confluence:page:2000"),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_empty_source_version_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), source_version=""),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_missing_jira_keys_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), jira_keys=_DELETE),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_missing_relation_ids_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), relation_ids=_DELETE),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_schema_invalid_canonical_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), unexpected_field="x"),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_wrong_source_system_is_rejected() -> None:
    _reject(
        _mutate_canonical(_valid_result(), source_type="attachment_text"),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


def test_duplicate_jira_keys_in_canonical_are_rejected() -> None:
    _reject(
        _mutate_canonical(
            _valid_result(), jira_keys=["SVMCSPEN-20", "SVMCSPEN-20"]
        ),
        _Category.CANONICAL_DOCUMENT_INVALID,
    )


# --- Chunk provenance ---------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("document_id", "confluence:page:2000"),
        ("source_system", "git"),
        ("source_type", "code_file"),
        ("title", "Different"),
        ("space_key", "OTHER"),
        ("page_id", "2000"),
        ("source_version", "99"),
        ("updated_at", "2000-01-01T00:00:00Z"),
    ],
)
def test_each_mismatched_canonical_chunk_field_is_rejected(
    field: str, value: str
) -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, **{field: value}),
        _Category.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    )


def test_zero_chunks_is_accepted() -> None:
    _validator().validate(_valid_result(chunk_count=0))


def test_duplicate_chunk_id_is_rejected() -> None:
    result = _valid_result()
    first_id = result.enriched_chunks[0]["chunk_id"]
    _reject(
        _mutate_chunk(result, 1, chunk_id=first_id),
        _Category.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    )


def test_chunk_content_hash_mismatch_is_rejected() -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, text="tampered text"),
        _Category.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    )


def test_non_pristine_chunk_acl_tags_are_rejected() -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, acl_tags=["space:SPACE"]),
        _Category.ACL_STAGE_INPUT_NOT_PRISTINE,
    )


def test_chunk_jira_key_array_mismatch_is_rejected() -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, jira_keys=[]),
        _Category.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    )


def test_chunk_relation_id_array_mismatch_is_rejected() -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, relation_ids=[]),
        _Category.CANONICAL_CHUNK_IDENTITY_MISMATCH,
    )


def test_schema_invalid_chunk_is_rejected() -> None:
    _reject(
        _mutate_chunk(_valid_result(), 0, token_count=-1),
        _Category.CHUNK_RECORD_INVALID,
    )


# --- Relation provenance ------------------------------------------------------


def test_schema_valid_wrong_target_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, target_id="jira:issue:SVMCSPEN-999"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_relation_id_in_record_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, relation_id="rel:1111111111111111"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_source_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, source_id="confluence:page:2000"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_relation_type_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, relation_type="links_to_page"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_evidence_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, evidence="regex:title"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_confidence_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, confidence=0.5),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_wrong_resolution_status_is_rejected() -> None:
    _reject(
        _mutate_relation(_valid_result(), 0, resolution_status="resolved"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_swapped_relation_order_is_rejected() -> None:
    result = _valid_result()
    swapped = (result.relations[1], result.relations[0])
    _reject(
        _rebuild(result, relations=swapped),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_canonical_relation_id_mismatch_is_rejected() -> None:
    result = _valid_result()
    canonical = deepcopy(result.enriched_canonical_document)
    forged = ["rel:0000000000000000", canonical["relation_ids"][1]]
    canonical["relation_ids"] = forged
    chunks = []
    for chunk in deepcopy(result.enriched_chunks):
        chunk = dict(chunk)
        chunk["relation_ids"] = list(forged)
        chunks.append(chunk)
    _reject(
        _rebuild(result, canonical=canonical, chunks=tuple(chunks)),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )


def test_relation_failures_do_not_leak_keys_or_ids() -> None:
    error = _reject(
        _mutate_relation(_valid_result(), 0, target_id="jira:issue:SVMCSPEN-999"),
        _Category.M6E_RELATION_PROVENANCE_INVALID,
    )
    message = str(error)
    assert message == "m6e_relation_provenance_invalid"
    assert "SVMCSPEN" not in message
    assert "rel:" not in message
    assert "jira:issue" not in message


# --- Quality provenance -------------------------------------------------------


def test_duplicate_unique_candidates_are_rejected() -> None:
    result = _valid_result()
    _reject(
        _mutate_quality(
            result,
            unique=(
                "SVMCSPEN-20",
                "SHA-256",
                "SVMCSPEN-3",
                "ISO-8601",
                "SVMCSPEN-20",
            ),
        ),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_allowlisted_and_outside_must_be_disjoint() -> None:
    _reject(
        _mutate_quality(
            _valid_result(),
            allow=("SVMCSPEN-20", "SVMCSPEN-3"),
            outside=("SVMCSPEN-3", "ISO-8601"),
        ),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_allowlisted_and_outside_must_fully_partition_unique() -> None:
    _reject(
        _mutate_quality(
            _valid_result(),
            unique=("SVMCSPEN-20", "SHA-256", "SVMCSPEN-3", "ISO-8601", "EXTRA-1"),
        ),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_correct_sets_in_wrong_order_are_rejected() -> None:
    _reject(
        _mutate_quality(
            _valid_result(),
            outside=("ISO-8601", "SHA-256"),
        ),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_allowlisted_tuple_must_equal_canonical_jira_keys() -> None:
    _reject(
        _mutate_quality(_valid_result(), allow=("SVMCSPEN-20",)),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


# --- Metric provenance --------------------------------------------------------


def test_unknown_metric_key_is_rejected() -> None:
    _reject(
        _mutate_metrics(_valid_result(), surprise=1),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_missing_metric_key_is_rejected() -> None:
    _reject(
        _mutate_metrics(_valid_result(), relations_total=_DELETE),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_bool_metric_value_is_rejected() -> None:
    _reject(
        _mutate_metrics(_valid_result(), documents_enriched=True),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_negative_metric_value_is_rejected() -> None:
    _reject(
        _mutate_metrics(_valid_result(), relations_total=-1),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


@pytest.mark.parametrize(
    "key",
    [
        "unique_key_like_count",
        "allowlisted_unique_count",
        "outside_allowlist_unique_count",
        "relations_total",
        "documents_enriched",
        "chunks_enriched",
    ],
)
def test_each_independently_derived_metric_is_checked(key: str) -> None:
    result = _valid_result()
    wrong = result.metrics[key] + 1
    _reject(
        _mutate_metrics(result, **{key: wrong}),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_candidate_occurrences_below_unique_count_is_rejected() -> None:
    result = _valid_result()
    below = result.metrics["unique_key_like_count"] - 1
    _reject(
        _mutate_metrics(result, candidate_occurrences=below),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_duplicate_occurrence_arithmetic_mismatch_is_rejected() -> None:
    result = _valid_result()
    wrong_duplicate = result.metrics["duplicate_occurrences"] + 5
    _reject(
        _mutate_metrics(result, duplicate_occurrences=wrong_duplicate),
        _Category.M6E_RESULT_PROVENANCE_INVALID,
    )


def test_large_but_algebraically_consistent_occurrence_count_is_accepted() -> None:
    result = _valid_result()
    unique_count = result.metrics["unique_key_like_count"]
    high = _mutate_metrics(
        result,
        candidate_occurrences=1000,
        duplicate_occurrences=1000 - unique_count,
    )
    _validator().validate(high)


def test_duplicate_occurrence_sequence_is_not_reconstructable_from_result() -> None:
    result = _valid_result()
    quality = result.quality_observation

    # Only deduplicated candidates are retained; the raw occurrence multiset
    # (which would reveal per-key duplicate counts) is not stored anywhere.
    assert len(quality.unique_key_like_candidates) == len(
        set(quality.unique_key_like_candidates)
    )
    assert all("occurrence" not in name for name in vars(quality))
    assert not hasattr(result, "occurrences")

    # The boundary accepts the aggregate purely on algebra, so it cannot and
    # does not reconstruct which candidate occurred how many times.
    unique_count = result.metrics["unique_key_like_count"]
    _validator().validate(
        _mutate_metrics(
            result,
            candidate_occurrences=500,
            duplicate_occurrences=500 - unique_count,
        )
    )
