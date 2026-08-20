from __future__ import annotations

from copy import deepcopy

import pytest

from knowledgenexus.foundation.application.use_cases.project_one_page_export import (
    OnePageExportProjection,
    OnePageExportProjectionError,
    ProjectOnePageExport,
)
from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
    ConfluenceAclMaterializationResult,
)
from knowledgenexus.foundation.domain.models.chunking_profile import (
    ChunkingProfile,
    TokenizerAsset,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    JiraRelationQualityObservation,
)
from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
    ONE_PAGE_EXPORT_MODE,
    ONE_PAGE_SCHEMAS_VERSION,
    ONE_PAGE_SOURCE_ID,
    OnePageExportProfileBundle,
)
from knowledgenexus.foundation.domain.records import (
    ACLRecordBuilder,
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
    RelationRecordBuilder,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)

DOCUMENT_ID = "confluence:page:1000"
ACL_ID = "acl:confluence:page:1000"
PAGE_ID = "1000"
SPACE_KEY = "SVMC"
UPDATED_AT = "2026-07-20T01:02:03Z"
CREATED_AT = "2026-07-22T00:00:00Z"
EXTRACTED_AT = "2026-07-22T00:00:00Z"
CRAWLER = "kn-foundation/1.0 (offline)"
ACL_TAGS = ["space:SVMC"]


def _quality(**overrides: object) -> AclQualityObservation:
    fields: dict[str, object] = {
        "restriction_observations_total": 1,
        "available_observations": 1,
        "unavailable_observations": 0,
        "restricted_levels": 0,
        "unrestricted_levels": 1,
        "observed_user_envelope_occurrences": 0,
        "observed_group_envelope_occurrences": 0,
        "unique_valid_user_principals": 0,
        "unique_valid_group_principals": 0,
        "non_enforceable_user_occurrences": 0,
        "non_enforceable_group_occurrences": 0,
        "user_principals_dropped_by_intersection": 0,
        "group_principals_dropped_by_intersection": 0,
        "effective_users": 0,
        "effective_groups": 0,
        "default_deny_applied": False,
        "manual_review_required": False,
        "reason_codes": (),
    }
    fields.update(overrides)
    return AclQualityObservation(**fields)  # type: ignore[arg-type]


def _jira_quality(**overrides: object) -> JiraRelationQualityObservation:
    fields: dict[str, object] = {
        "unique_key_like_candidates": ("SVMCSPEN-1",),
        "allowlisted_keys": ("SVMCSPEN-1",),
        "outside_allowlist_keys": (),
    }
    fields.update(overrides)
    return JiraRelationQualityObservation(**fields)  # type: ignore[arg-type]


def _canonical(
    *,
    space_key: object = SPACE_KEY,
    jira_keys: list[str] | None = None,
    relation_ids: list[str] | None = None,
) -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id=DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text="Body mentions SVMCSPEN-1 once.",
        acl_id=ACL_ID,
        crawled_at=CREATED_AT,
        title="Fixture Foundation",
        space_key=space_key,
        page_id=PAGE_ID,
        source_version="9",
        jira_keys=jira_keys or [],
        relation_ids=relation_ids or [],
        updated_at=UPDATED_AT,
    )


def _chunk(
    index: int,
    *,
    space_key: object = SPACE_KEY,
    acl_tags: list[str] | None = None,
    jira_keys: list[str] | None = None,
    relation_ids: list[str] | None = None,
    chunker_version: str = "1.3.0",
) -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=f"chunk:confluence:{index:016x}",
        document_id=DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        text=f"Fixture Foundation\n\nchunk text {index}",
        content_kind="prose",
        language="unknown",
        token_count=7,
        acl_tags=acl_tags if acl_tags is not None else list(ACL_TAGS),
        chunker_version=chunker_version,
        title="Fixture Foundation",
        heading_path=["Fixture Foundation"],
        space_key=space_key,
        page_id=PAGE_ID,
        jira_keys=jira_keys or [],
        relation_ids=relation_ids or [],
        source_version="9",
        updated_at=UPDATED_AT,
    )


def _relation(index: int = 0, *, target: str = "SVMCSPEN-1") -> dict[str, object]:
    return RelationRecordBuilder.build(
        relation_id=f"rel:{index:016x}",
        source_id=DOCUMENT_ID,
        target_id=f"jira:issue:{target}",
        relation_type="mentions_jira_key",
        evidence="regex:page_body",
        confidence=0.95,
        resolution_status="unresolved_without_jira_api",
        created_at=CREATED_AT,
    )


def _acl_record(
    *, acl_tags: list[str] | None = None, source_system: str = "confluence"
) -> dict[str, object]:
    return ACLRecordBuilder.build(
        acl_id=ACL_ID,
        document_id=DOCUMENT_ID,
        source_system=source_system,
        is_restricted=False,
        acl_tags=acl_tags if acl_tags is not None else list(ACL_TAGS),
        acl_extraction_status="ok",
        extracted_at=EXTRACTED_AT,
        crawler_identity=CRAWLER,
        acl_confidence="exact",
        restriction_inherited=False,
        restriction_source_page_ids=[],
        allowed_users=[],
        allowed_groups=[],
    )


def _result(
    *,
    canonical: dict[str, object] | None = None,
    chunks: tuple[dict[str, object], ...] | None = None,
    relations: tuple[dict[str, object], ...] | None = None,
    acl_record: dict[str, object] | None = None,
    jira_quality_observation: JiraRelationQualityObservation | None = None,
    jira_metrics: dict[str, object] | None = None,
) -> ConfluenceAclMaterializationResult:
    return ConfluenceAclMaterializationResult(
        enriched_canonical_document=canonical if canonical is not None else _canonical(),
        enriched_chunks=chunks if chunks is not None else (_chunk(0),),
        relations=relations if relations is not None else (),
        acl_record=acl_record if acl_record is not None else _acl_record(),
        quality_observation=_quality(),
        metrics={"acl_records_total": 1},
        jira_quality_observation=(
            jira_quality_observation
            if jira_quality_observation is not None
            else _jira_quality(allowlisted_keys=(), unique_key_like_candidates=(), )
        ),
        jira_metrics=jira_metrics if jira_metrics is not None else {"relations_total": 0},
    )


def _chunking_profile() -> ChunkingProfile:
    return ChunkingProfile(
        chunker_version="1.3.0",
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


def _bundle() -> OnePageExportProfileBundle:
    return OnePageExportProfileBundle(
        chunking_profile=_chunking_profile(),
        jira_relation_profile=JiraRelationProfile(
            schema_version=1,
            extraction_mode=JIRA_EXTRACTION_MODE,
            key_pattern=JIRA_KEY_PATTERN,
            allowed_project_keys=("SVMCSPEN",),
        ),
        normalized_embedding_profile_text="embedding-text",
        normalized_jira_relation_profile_text="jira-text",
    )


def _project(result: ConfluenceAclMaterializationResult) -> OnePageExportProjection:
    return ProjectOnePageExport(schema_validator=FoundationSchemaValidator()).execute(
        acl_result=result,
        profile_bundle=_bundle(),
    )


# --- success -----------------------------------------------------------------


def test_success_projects_exact_streams_and_scopes() -> None:
    relation = _relation()
    canonical = _canonical(
        jira_keys=["SVMCSPEN-1"], relation_ids=[relation["relation_id"]]
    )
    chunk = _chunk(
        0, jira_keys=["SVMCSPEN-1"], relation_ids=[relation["relation_id"]]
    )
    result = _result(canonical=canonical, chunks=(chunk,), relations=(relation,))

    projection = _project(result)

    assert projection.dataset_name == ONE_PAGE_DATASET_NAME
    assert projection.source_id == ONE_PAGE_SOURCE_ID
    assert projection.export_mode == ONE_PAGE_EXPORT_MODE
    assert projection.schemas_version == ONE_PAGE_SCHEMAS_VERSION
    assert projection.documents == (canonical,)
    assert projection.chunks == (chunk,)
    assert projection.relations == (relation,)
    assert projection.acl == (result.acl_record,)
    assert projection.media_assets == ()
    assert projection.symbols == ()
    assert projection.sync_state == ()
    assert projection.tombstones == ()
    assert projection.source_scopes == {
        "confluence": {
            "source_ids": ["confluence_svmc_spensrv"],
            "space_keys": ["SVMC"],
            "page_ids": ["1000"],
        }
    }
    assert projection.chunker_version == "1.3.0"
    assert projection.active_profile == "medium"
    assert projection.profile_status == "provisional_until_benchmark"
    assert len(projection.config_hash) == 64
    assert projection.jira_quality_observation == result.jira_quality_observation
    assert projection.jira_metrics == result.jira_metrics
    assert projection.acl_quality_observation == result.quality_observation
    assert projection.acl_metrics == result.metrics


def test_zero_chunks_and_relations_is_valid() -> None:
    result = _result(chunks=(), relations=())
    projection = _project(result)
    assert projection.chunks == ()
    assert projection.relations == ()


def test_input_result_is_not_mutated() -> None:
    result = _result()
    before = deepcopy(result)
    _project(result)
    assert result == before


def test_projection_repr_hides_contents() -> None:
    projection = _project(_result())
    rendered = repr(projection)
    assert "Fixture Foundation" not in rendered
    assert PAGE_ID not in rendered


# --- space identity (R3) ------------------------------------------------------


@pytest.mark.parametrize("space_key", [None, "NOTSVMC", "svmc", ""])
def test_non_svmc_or_unrepresentable_space_key_is_export_projection_failure(
    space_key: object,
) -> None:
    # A null/unrepresentable space_key is a *valid ACL outcome* per
    # ACL_MATERIALIZATION_SPEC §5.4, but is still an export_projection failure
    # here because ONE_PAGE_EXPORT_SPEC §4 requires canonical space_key==SVMC.
    canonical = _canonical(space_key=space_key)
    result = _result(canonical=canonical, chunks=(_chunk(0, space_key=space_key),))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


# --- graph invariants ---------------------------------------------------------


def test_wrong_source_system_or_type_is_rejected() -> None:
    canonical = _canonical()
    canonical["source_type"] = "code_file"
    result = _result(canonical=canonical)
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_acl_record_document_identity_mismatch_is_rejected() -> None:
    acl_record = _acl_record()
    acl_record["document_id"] = "confluence:page:9999"
    result = _result(acl_record=acl_record)
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_chunk_acl_tags_must_match_acl_record_exactly() -> None:
    result = _result(chunks=(_chunk(0, acl_tags=["space:SVMC", "user:extra"]),))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_chunk_identity_field_mismatch_is_rejected() -> None:
    chunk = _chunk(0)
    chunk["page_id"] = "9999"
    result = _result(chunks=(chunk,))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_duplicate_chunk_ids_are_rejected() -> None:
    chunk = _chunk(0)
    result = _result(chunks=(chunk, dict(chunk)))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_duplicate_relation_ids_are_rejected() -> None:
    relation = _relation()
    canonical = _canonical(relation_ids=[relation["relation_id"], relation["relation_id"]])
    result = _result(canonical=canonical, relations=(relation, dict(relation)))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_canonical_relation_ids_must_equal_exported_order_exactly() -> None:
    relation = _relation()
    canonical = _canonical(relation_ids=["rel:0000000000000099"])
    result = _result(canonical=canonical, relations=(relation,))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_relation_source_id_mismatch_is_rejected() -> None:
    relation = _relation()
    relation["source_id"] = "confluence:page:9999"
    canonical = _canonical(relation_ids=[relation["relation_id"]])
    result = _result(canonical=canonical, relations=(relation,))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_unresolved_chunk_relation_reference_is_rejected() -> None:
    chunk = _chunk(0, relation_ids=["rel:0000000000000099"])
    result = _result(chunks=(chunk,), relations=())
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_chunker_version_mismatch_with_profile_bundle_is_rejected() -> None:
    result = _result(chunks=(_chunk(0, chunker_version="9.9.9"),))
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


def test_schema_invalid_canonical_document_is_rejected() -> None:
    canonical = _canonical()
    del canonical["document_id"]
    result = _result(canonical=canonical)
    with pytest.raises(OnePageExportProjectionError):
        _project(result)


# --- constructor validation ---------------------------------------------------


def test_execute_rejects_wrong_typed_inputs() -> None:
    use_case = ProjectOnePageExport(schema_validator=FoundationSchemaValidator())
    with pytest.raises(TypeError):
        use_case.execute(acl_result="not-a-result", profile_bundle=_bundle())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        use_case.execute(acl_result=_result(), profile_bundle="not-a-bundle")  # type: ignore[arg-type]


def test_constructor_rejects_invalid_schema_validator() -> None:
    with pytest.raises(TypeError):
        ProjectOnePageExport(schema_validator=object())  # type: ignore[arg-type]
