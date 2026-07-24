from __future__ import annotations

from copy import deepcopy

import pytest

from knowledgenexus.foundation.application.use_cases import (
    BuildConfluenceJiraRelations,
    MaterializeConfluenceAcl,
)
from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    ChunkingResult,
    ConfluenceAclMaterializationResult,
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

_Category = AclMaterializationFailureCategory

SELECTED = "1000"
DOCUMENT_ID = "confluence:page:1000"
ACL_ID = "acl:confluence:page:1000"
BODY = "SVMCSPEN-20 and SHA-256 then SVMCSPEN-3, SVMCSPEN-20 and ISO-8601."
UPDATED_AT = "2026-07-20T01:02:03Z"
CREATED_AT = "2026-07-22T00:00:00Z"
CRAWLER = "kn-foundation/1.0 (offline)"
EXTRACTED_AT = "2026-07-22T00:00:00Z"
METRIC_KEYS = frozenset(
    {
        "acl_records_total",
        "chunks_total",
        "chunks_acl_changed",
        "restriction_observations_total",
        "available_observations",
        "unavailable_observations",
        "restricted_levels",
        "unrestricted_levels",
        "observed_user_envelope_occurrences",
        "observed_group_envelope_occurrences",
        "unique_valid_user_principals",
        "unique_valid_group_principals",
        "non_enforceable_user_occurrences",
        "non_enforceable_group_occurrences",
        "user_principals_dropped_by_intersection",
        "group_principals_dropped_by_intersection",
        "effective_users",
        "effective_groups",
        "default_deny_records",
        "partial_acl_records",
        "unavailable_acl_records",
        "manual_review_records",
    }
)


# --- fixtures -----------------------------------------------------------------


def _profile() -> JiraRelationProfile:
    return JiraRelationProfile(
        schema_version=1,
        extraction_mode=JIRA_EXTRACTION_MODE,
        key_pattern=JIRA_KEY_PATTERN,
        allowed_project_keys=("SVMCSPEN",),
    )


def _canonical(space_key: str | None) -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id=DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=BODY,
        acl_id=ACL_ID,
        crawled_at=CREATED_AT,
        title="Fixture Foundation",
        space_key=space_key,
        page_id=SELECTED,
        source_version="9",
        jira_keys=[],
        relation_ids=[],
        updated_at=UPDATED_AT,
    )


def _chunk(index: int, space_key: str | None) -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=f"chunk:confluence:{index:016x}",
        document_id=DOCUMENT_ID,
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
        space_key=space_key,
        page_id=SELECTED,
        jira_keys=[],
        relation_ids=[],
        source_version="9",
        updated_at=UPDATED_AT,
    )


def _build_result(*, chunk_count: int = 2, space_key: str | None = "SPACE"):
    use_case = BuildConfluenceJiraRelations(
        profile=_profile(),
        document_id_generator=DocumentIdGenerator,
        relation_id_generator=RelationIdGenerator,
        relation_record_builder=RelationRecordBuilder,
        schema_validator=FoundationSchemaValidator(),
    )
    chunks = ChunkingResult(
        records=tuple(_chunk(i, space_key) for i in range(chunk_count)),
        metrics={"chunks_total": chunk_count, "chunks_over_hard_max": 0},
    )
    return use_case.execute(
        normalized_body_text=BODY,
        canonical_document=_canonical(space_key),
        chunking_result=chunks,
        created_at=CREATED_AT,
    )


def _materialize(
    result,
    observations,
    *,
    crawler_identity: object = CRAWLER,
    extracted_at: object = EXTRACTED_AT,
) -> ConfluenceAclMaterializationResult:
    use_case = MaterializeConfluenceAcl(schema_validator=FoundationSchemaValidator())
    return use_case.execute(
        jira_relation_result=result,
        restriction_observations=observations,
        crawler_identity=crawler_identity,
        extracted_at=extracted_at,
    )


def _reject(observations, category, *, result=None, **kwargs):
    with pytest.raises(AclMaterializationError) as exc:
        _materialize(result or _build_result(), observations, **kwargs)
    assert exc.value.category is category
    return exc.value


def _unavailable(page_id: str, *, status: int = 404) -> dict[str, object]:
    return {
        "source_page_id": page_id,
        "http_status": status,
        "classification": "unavailable",
        "users": [],
        "groups": [],
    }


def _unrestricted(page_id: str) -> dict[str, object]:
    return {
        "source_page_id": page_id,
        "http_status": 200,
        "classification": "unrestricted",
        "users": [],
        "groups": [],
    }


def _restricted(page_id: str, *, users=None, groups=None) -> dict[str, object]:
    return {
        "source_page_id": page_id,
        "http_status": 200,
        "classification": "restricted",
        "users": list(users or []),
        "groups": list(groups or []),
    }


def _user(**fields: str) -> dict[str, str]:
    return dict(fields)


def _group(name: str) -> dict[str, str]:
    return {"name": name}


# --- unavailable chain (spec §G) ---------------------------------------------


def test_single_unavailable_selected_page_is_deny_safe() -> None:
    out = _materialize(_build_result(), (_unavailable(SELECTED),))
    record = out.acl_record

    assert record["is_restricted"] is True
    assert record["acl_tags"] == ["restricted:unresolved"]
    assert record["acl_extraction_status"] == "unavailable"
    assert record["acl_confidence"] == "approximate"
    # Evidence fields are omitted for an unavailable chain.
    for omitted in (
        "restriction_inherited",
        "restriction_source_page_ids",
        "allowed_users",
        "allowed_groups",
    ):
        assert omitted not in record
    assert out.metrics["chunks_acl_changed"] == 0
    assert out.metrics["unavailable_acl_records"] == 1
    assert out.quality_observation.reason_codes == (
        "restriction_observations_unavailable",
    )


def test_mixed_available_and_unavailable_is_unavailable() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="Admin")]),
        _unavailable("8", status=403),
        _unrestricted(SELECTED),
    )
    out = _materialize(_build_result(), observations)

    assert out.acl_record["acl_extraction_status"] == "unavailable"
    # Available restricted observation still contributes safe projection counts.
    assert out.metrics["restricted_levels"] == 1
    assert out.metrics["unique_valid_user_principals"] == 1
    assert out.metrics["observed_user_envelope_occurrences"] == 1
    # But no intersection is computed for an unavailable chain.
    assert out.metrics["effective_users"] == 0
    assert out.metrics["user_principals_dropped_by_intersection"] == 0


def test_all_unavailable_is_deny_safe() -> None:
    observations = (_unavailable("7"), _unavailable(SELECTED, status=401))
    out = _materialize(_build_result(), observations)

    assert out.acl_record["acl_tags"] == ["restricted:unresolved"]
    assert out.metrics["unavailable_observations"] == 2
    assert out.metrics["available_observations"] == 0


def test_unavailable_with_non_enforceable_user_keeps_projection_reason() -> None:
    observations = (
        _unavailable("7"),
        _restricted(
            SELECTED, users=[_user(userKey="ok"), _user(username="no-key")]
        ),
    )
    out = _materialize(_build_result(), observations)

    assert out.acl_record["acl_extraction_status"] == "unavailable"
    # unavailable + applicable projection reason, but never intersection reasons.
    assert out.quality_observation.reason_codes == (
        "restriction_observations_unavailable",
        "non_enforceable_user_principal",
    )
    assert out.metrics["non_enforceable_user_occurrences"] == 1


def test_unavailable_omits_evidence_even_with_known_principals() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="Admin")]),
        _unavailable(SELECTED),
    )
    record = _materialize(_build_result(), observations).acl_record
    assert "allowed_users" not in record
    assert "restriction_source_page_ids" not in record


# --- complete unrestricted chain (spec §H) -----------------------------------


def test_unrestricted_representable_space_tag() -> None:
    out = _materialize(_build_result(space_key="SPACE"), (_unrestricted(SELECTED),))
    record = out.acl_record

    assert record["is_restricted"] is False
    assert record["acl_tags"] == ["space:SPACE"]
    assert record["acl_extraction_status"] == "ok"
    assert record["acl_confidence"] == "exact"
    assert record["restriction_inherited"] is False
    assert record["restriction_source_page_ids"] == []
    assert record["allowed_users"] == []
    assert record["allowed_groups"] == []
    assert out.quality_observation.reason_codes == ()
    assert out.metrics["chunks_acl_changed"] == out.metrics["chunks_total"] == 2


def test_null_space_key_is_deny_safe_but_not_restricted() -> None:
    out = _materialize(_build_result(space_key=None), (_unrestricted(SELECTED),))
    record = out.acl_record

    assert record["is_restricted"] is False
    assert record["acl_tags"] == ["restricted:unresolved"]
    assert record["acl_extraction_status"] == "partial"
    assert record["acl_confidence"] == "approximate"
    assert out.quality_observation.reason_codes == ("space_tag_unrepresentable",)
    # Deny-safe fallback equals the pristine tag, so nothing changed.
    assert out.metrics["chunks_acl_changed"] == 0


@pytest.mark.parametrize("space_key", ["svmc", "SPA-CE", "space key", "Space", ""])
def test_unrepresentable_space_keys_fall_back_without_repair(space_key: str) -> None:
    out = _materialize(
        _build_result(space_key=space_key), (_unrestricted(SELECTED),)
    )
    record = out.acl_record
    assert record["is_restricted"] is False
    assert record["acl_tags"] == ["restricted:unresolved"]
    assert record["acl_extraction_status"] == "partial"
    assert out.quality_observation.reason_codes == ("space_tag_unrepresentable",)


def test_unrestricted_emits_empty_audit_arrays() -> None:
    record = _materialize(_build_result(), (_unrestricted(SELECTED),)).acl_record
    assert record["allowed_users"] == []
    assert record["allowed_groups"] == []
    assert record["restriction_source_page_ids"] == []


# --- complete restricted chain (spec §I) -------------------------------------


def test_selected_only_restriction_is_not_inherited() -> None:
    out = _materialize(
        _build_result(), (_restricted(SELECTED, users=[_user(userKey="Admin")]),)
    )
    record = out.acl_record
    assert record["is_restricted"] is True
    assert record["restriction_inherited"] is False
    assert record["restriction_source_page_ids"] == [SELECTED]
    assert record["acl_tags"] == ["user:admin"]


def test_ancestor_only_restriction_is_inherited() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="Admin")]),
        _unrestricted(SELECTED),
    )
    record = _materialize(_build_result(), observations).acl_record
    assert record["is_restricted"] is True
    assert record["restriction_inherited"] is True
    assert record["restriction_source_page_ids"] == ["7"]


def test_ancestor_and_selected_restriction_source_order() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="Admin")]),
        _unrestricted("8"),
        _restricted("9", users=[_user(userKey="Admin")]),
        _restricted(SELECTED, users=[_user(userKey="Admin")]),
    )
    record = _materialize(_build_result(), observations).acl_record
    assert record["restriction_source_page_ids"] == ["7", "9", SELECTED]
    assert record["restriction_inherited"] is True


def test_restricted_source_ids_follow_exact_chain_order() -> None:
    observations = (
        _restricted("30", users=[_user(userKey="a")]),
        _restricted("10", users=[_user(userKey="a")]),
        _restricted("20", users=[_user(userKey="a")]),
        _restricted(SELECTED, users=[_user(userKey="a")]),
    )
    record = _materialize(_build_result(), observations).acl_record
    # Chain order, never sorted.
    assert record["restriction_source_page_ids"] == ["30", "10", "20", SELECTED]


# --- effective intersection (spec §K, §L, §M) --------------------------------


def test_same_user_survives_single_level() -> None:
    out = _materialize(
        _build_result(),
        (_restricted(SELECTED, users=[_user(userKey="Alpha"), _user(userKey="Beta")]),),
    )
    assert out.acl_record["acl_tags"] == ["user:alpha", "user:beta"]
    assert out.metrics["effective_users"] == 2
    assert out.metrics["user_principals_dropped_by_intersection"] == 0
    assert out.acl_record["acl_extraction_status"] == "ok"


def test_same_group_survives_across_levels() -> None:
    observations = (
        _restricted("7", groups=[_group("Platform")]),
        _restricted(SELECTED, groups=[_group("platform")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["group:platform"]
    assert out.metrics["effective_groups"] == 1
    assert out.metrics["group_principals_dropped_by_intersection"] == 0


def test_different_users_drop_to_empty_intersection() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="alpha")]),
        _restricted(SELECTED, users=[_user(userKey="beta")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["restricted:unresolved"]
    assert out.metrics["effective_users"] == 0
    assert out.metrics["user_principals_dropped_by_intersection"] == 2
    assert out.acl_record["acl_extraction_status"] == "partial"
    assert out.quality_observation.reason_codes == (
        "user_principal_dropped_by_intersection",
        "empty_effective_intersection",
    )


def test_different_groups_drop() -> None:
    observations = (
        _restricted("7", groups=[_group("a")]),
        _restricted(SELECTED, groups=[_group("b")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.metrics["group_principals_dropped_by_intersection"] == 2
    assert out.acl_record["acl_tags"] == ["restricted:unresolved"]


def test_partial_surviving_intersection() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="alpha"), _user(userKey="beta")]),
        _restricted(SELECTED, users=[_user(userKey="alpha"), _user(userKey="carol")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["user:alpha"]
    assert out.metrics["effective_users"] == 1
    # union {alpha,beta,carol} minus effective {alpha} = 2 unique dropped.
    assert out.metrics["user_principals_dropped_by_intersection"] == 2
    assert out.acl_record["acl_extraction_status"] == "partial"


def test_one_namespace_empty_while_other_survives() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="alpha")], groups=[_group("g")]),
        _restricted(SELECTED, users=[_user(userKey="alpha")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["user:alpha"]
    assert out.metrics["effective_users"] == 1
    assert out.metrics["effective_groups"] == 0
    assert out.metrics["group_principals_dropped_by_intersection"] == 1


def test_user_and_group_same_text_stay_separate() -> None:
    observations = (
        _restricted(
            "7", users=[_user(userKey="team")], groups=[_group("team")]
        ),
        _restricted(
            SELECTED, users=[_user(userKey="team")], groups=[_group("team")]
        ),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["group:team", "user:team"]
    assert out.metrics["effective_users"] == 1
    assert out.metrics["effective_groups"] == 1


def test_single_level_has_no_intersection_drop() -> None:
    out = _materialize(
        _build_result(),
        (_restricted(SELECTED, users=[_user(userKey="a"), _user(userKey="b")]),),
    )
    assert out.metrics["user_principals_dropped_by_intersection"] == 0
    assert out.acl_record["acl_extraction_status"] == "ok"


def test_casing_variants_collapse_and_keep_earliest_representation() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="Admin")]),
        _restricted(SELECTED, users=[_user(userKey="ADMIN")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_tags"] == ["user:admin"]
    # Audit keeps the earliest exact representation (M6F-A rule).
    assert out.acl_record["allowed_users"] == ["Admin"]
    assert out.metrics["unique_valid_user_principals"] == 1


def test_non_enforceable_principal_makes_result_partial() -> None:
    out = _materialize(
        _build_result(),
        (
            _restricted(
                SELECTED,
                users=[_user(userKey="ok"), _user(username="no-key")],
            ),
        ),
    )
    assert out.acl_record["acl_tags"] == ["user:ok"]
    assert out.acl_record["acl_extraction_status"] == "partial"
    assert out.metrics["non_enforceable_user_occurrences"] == 1
    assert "non_enforceable_user_principal" in out.quality_observation.reason_codes


def test_all_principals_non_enforceable_is_deny_safe() -> None:
    out = _materialize(
        _build_result(),
        (_restricted(SELECTED, users=[_user(username="x"), _user(accountId="y")]),),
    )
    assert out.acl_record["acl_tags"] == ["restricted:unresolved"]
    assert out.metrics["observed_user_envelope_occurrences"] == 2
    assert out.metrics["unique_valid_user_principals"] == 0
    assert out.metrics["non_enforceable_user_occurrences"] == 2
    assert out.quality_observation.reason_codes == (
        "non_enforceable_user_principal",
        "empty_effective_intersection",
    )


# --- audit union vs enforcement (spec §J) ------------------------------------


def test_audit_union_contains_dropped_but_valid_principals() -> None:
    observations = (
        _restricted("7", users=[_user(userKey="alpha"), _user(userKey="beta")]),
        _restricted(SELECTED, users=[_user(userKey="alpha"), _user(userKey="carol")]),
    )
    record = _materialize(_build_result(), observations).acl_record
    # Audit union across restricted levels, sorted by canonical identity.
    assert record["allowed_users"] == ["alpha", "beta", "carol"]
    # Effective ACL is only the intersection.
    assert record["acl_tags"] == ["user:alpha"]


def test_non_enforceable_values_never_enter_audit_fields() -> None:
    record = _materialize(
        _build_result(),
        (
            _restricted(
                SELECTED,
                users=[_user(userKey="real"), _user(username="ghost")],
                groups=[_group("grp")],
            ),
        ),
    ).acl_record
    assert record["allowed_users"] == ["real"]
    assert "ghost" not in record["allowed_users"]
    assert record["allowed_groups"] == ["grp"]


def test_audit_arrays_sorted_by_canonical_identity() -> None:
    record = _materialize(
        _build_result(),
        (
            _restricted(
                SELECTED,
                users=[_user(userKey="Zeta"), _user(userKey="alpha")],
                groups=[_group("Zulu"), _group("alpha")],
            ),
        ),
    ).acl_record
    assert record["allowed_users"] == ["alpha", "Zeta"]
    assert record["allowed_groups"] == ["alpha", "Zulu"]


# --- status / reason precedence (spec §N, §O) --------------------------------


def test_unavailable_beats_partial_and_ok() -> None:
    observations = (
        _unavailable("7"),
        _restricted(SELECTED, users=[_user(userKey="ok")]),
    )
    out = _materialize(_build_result(), observations)
    assert out.acl_record["acl_extraction_status"] == "unavailable"


def test_reason_codes_follow_fixed_policy_order() -> None:
    # Two levels whose users intersect to empty, plus a non-enforceable user.
    observations = (
        _restricted("7", users=[_user(userKey="alpha")]),
        _restricted(
            SELECTED,
            users=[_user(userKey="beta"), _user(username="no-key")],
        ),
    )
    out = _materialize(_build_result(), observations)
    codes = out.quality_observation.reason_codes
    # Fixed policy order, never incidental execution order.
    assert codes == (
        "non_enforceable_user_principal",
        "user_principal_dropped_by_intersection",
        "empty_effective_intersection",
    )


def test_ok_result_has_no_reason_codes() -> None:
    out = _materialize(
        _build_result(), (_restricted(SELECTED, users=[_user(userKey="a")]),)
    )
    assert out.quality_observation.reason_codes == ()
    assert out.acl_record["acl_extraction_status"] == "ok"
    assert out.acl_record["acl_confidence"] == "exact"


# --- ACLRecord construction (spec §R) ----------------------------------------


def test_acl_record_reuses_canonical_ids_and_is_schema_valid() -> None:
    out = _materialize(_build_result(), (_unrestricted(SELECTED),))
    record = out.acl_record
    assert record["acl_id"] == ACL_ID
    assert record["document_id"] == DOCUMENT_ID
    assert record["schema_version"] == "1.0"
    assert record["source_system"] == "confluence"
    # Independently re-validate the built record.
    FoundationSchemaValidator().validate_record("ACLRecord", record)


def test_crawler_identity_and_extracted_at_preserved_exactly() -> None:
    record = _materialize(
        _build_result(),
        (_unrestricted(SELECTED),),
        crawler_identity="  spaced-crawler  ",
        extracted_at="2026-07-22T00:00:00.123456+09:00",
    ).acl_record
    assert record["crawler_identity"] == "  spaced-crawler  "
    assert record["extracted_at"] == "2026-07-22T00:00:00.123456+09:00"


@pytest.mark.parametrize(
    "identity",
    ["", "   ", "line\nbreak", "tab\tchar", "bell\x07", "\x7fdel", 5, None],
)
def test_invalid_crawler_identity_is_sanitized(identity: object) -> None:
    error = _reject(
        (_unrestricted(SELECTED),),
        _Category.INVALID_CRAWLER_IDENTITY,
        crawler_identity=identity,
    )
    assert str(error) == "invalid_crawler_identity"


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-22",
        "2026-07-22T00:00:00",
        "not-a-date",
        "2026-13-01T00:00:00Z",
        "2026-07-22T00:00:00+99:00",
        20260722,
        None,
    ],
)
def test_invalid_extracted_at_is_sanitized(timestamp: object) -> None:
    error = _reject(
        (_unrestricted(SELECTED),),
        _Category.INVALID_EXTRACTED_AT,
        extracted_at=timestamp,
    )
    assert str(error) == "invalid_extracted_at"


def test_restricted_record_emits_all_evidence_fields() -> None:
    record = _materialize(
        _build_result(), (_restricted(SELECTED, users=[_user(userKey="a")]),)
    ).acl_record
    for field in (
        "restriction_inherited",
        "restriction_source_page_ids",
        "allowed_users",
        "allowed_groups",
    ):
        assert field in record


# --- boundary validation is not bypassed (spec §D) ---------------------------


def test_full_m6e_boundary_still_runs_on_typed_input() -> None:
    result = _build_result()
    tampered = deepcopy(result.enriched_canonical_document)
    tampered["acl_id"] = "acl:confluence:page:2000"
    broken = type(result)(
        enriched_canonical_document=tampered,
        enriched_chunks=deepcopy(result.enriched_chunks),
        relations=deepcopy(result.relations),
        quality_observation=result.quality_observation,
        metrics=deepcopy(result.metrics),
    )
    with pytest.raises(AclMaterializationError) as exc:
        _materialize(broken, (_unrestricted(SELECTED),))
    assert exc.value.category is _Category.CANONICAL_DOCUMENT_INVALID


def test_observation_chain_bound_to_canonical_page() -> None:
    # Selected observation page id does not equal the canonical page id.
    _reject(
        (_unrestricted("9999"),),
        _Category.CANONICAL_OBSERVATION_IDENTITY_MISMATCH,
    )


def test_empty_observation_chain_is_rejected() -> None:
    _reject((), _Category.INVALID_RESTRICTION_OBSERVATIONS)


def test_wrong_type_result_raises_type_error() -> None:
    use_case = MaterializeConfluenceAcl(schema_validator=FoundationSchemaValidator())
    with pytest.raises(TypeError):
        use_case.execute(
            jira_relation_result={"not": "a result"},
            restriction_observations=(_unrestricted(SELECTED),),
            crawler_identity=CRAWLER,
            extracted_at=EXTRACTED_AT,
        )


@pytest.mark.parametrize(
    "target, category",
    [
        ("canonical", _Category.CANONICAL_DOCUMENT_INVALID),
        ("chunk", _Category.CHUNK_RECORD_INVALID),
        ("relation", _Category.M6E_RELATION_PROVENANCE_INVALID),
    ],
)
def test_non_json_mutation_yields_precise_validator_category(
    target: str, category: AclMaterializationFailureCategory
) -> None:
    # A nested non-JSON value (a set) on a mutable M6E result must surface the
    # M6F-A validator's precise category, not the generic wrapper: the boundary
    # validation runs before any local snapshot/copy.
    result = _build_result()
    if target == "canonical":
        result.enriched_canonical_document["title"] = {1, 2}
    elif target == "chunk":
        result.enriched_chunks[0]["text"] = {1, 2}
    else:
        result.relations[0]["evidence"] = {1, 2}
    error = _reject((_unrestricted(SELECTED),), category, result=result)
    assert str(error) == category.value


# --- chunk propagation (spec §S) ---------------------------------------------


def test_only_acl_tags_change_on_chunks() -> None:
    result = _build_result()
    out = _materialize(result, (_unrestricted(SELECTED),))
    for original, enriched in zip(result.enriched_chunks, out.enriched_chunks):
        assert enriched["acl_tags"] == ["space:SPACE"]
        # Every other field identical.
        rebuilt = dict(enriched)
        rebuilt["acl_tags"] = original["acl_tags"]
        assert rebuilt == dict(original)


def test_chunk_identity_and_content_are_untouched() -> None:
    result = _build_result()
    out = _materialize(result, (_restricted(SELECTED, users=[_user(userKey="a")]),))
    for original, enriched in zip(result.enriched_chunks, out.enriched_chunks):
        for field in (
            "chunk_id",
            "document_id",
            "text",
            "content_hash",
            "token_count",
            "heading_path",
            "jira_keys",
            "relation_ids",
            "chunker_version",
        ):
            assert enriched[field] == original[field]


def test_every_output_chunk_tag_equals_record_tag() -> None:
    out = _materialize(
        _build_result(chunk_count=3),
        (_restricted(SELECTED, users=[_user(userKey="a")]),),
    )
    tags = out.acl_record["acl_tags"]
    assert all(chunk["acl_tags"] == tags for chunk in out.enriched_chunks)


def test_unresolved_to_unresolved_changed_count_zero() -> None:
    out = _materialize(_build_result(chunk_count=2), (_unavailable(SELECTED),))
    assert out.metrics["chunks_acl_changed"] == 0
    assert all(
        chunk["acl_tags"] == ["restricted:unresolved"]
        for chunk in out.enriched_chunks
    )


def test_resolved_acl_changes_all_nonzero_chunks() -> None:
    out = _materialize(
        _build_result(chunk_count=3),
        (_restricted(SELECTED, users=[_user(userKey="a")]),),
    )
    assert out.metrics["chunks_acl_changed"] == 3


def test_zero_chunks_is_valid() -> None:
    out = _materialize(_build_result(chunk_count=0), (_unrestricted(SELECTED),))
    assert out.enriched_chunks == ()
    assert out.metrics["chunks_total"] == 0
    assert out.metrics["chunks_acl_changed"] == 0
    assert out.acl_record["acl_tags"] == ["space:SPACE"]


def test_output_is_ownership_isolated_from_input() -> None:
    result = _build_result()
    out = _materialize(result, (_unrestricted(SELECTED),))
    assert out.enriched_chunks[0] is not result.enriched_chunks[0]
    # Mutating the output must not touch the input.
    out.enriched_chunks[0]["acl_tags"].append("user:injected")
    assert result.enriched_chunks[0]["acl_tags"] == ["restricted:unresolved"]


def test_inputs_are_not_mutated() -> None:
    result = _build_result()
    before_doc = deepcopy(result.enriched_canonical_document)
    before_chunks = deepcopy(result.enriched_chunks)
    before_relations = deepcopy(result.relations)

    _materialize(result, (_restricted(SELECTED, users=[_user(userKey="a")]),))

    assert result.enriched_canonical_document == before_doc
    assert result.enriched_chunks == before_chunks
    assert result.relations == before_relations


# --- canonical and relation preservation (spec §T) ---------------------------


def test_canonical_and_relations_preserved_but_isolated() -> None:
    result = _build_result()
    out = _materialize(result, (_unrestricted(SELECTED),))

    assert out.enriched_canonical_document == result.enriched_canonical_document
    assert out.enriched_canonical_document is not result.enriched_canonical_document
    assert out.relations == result.relations
    assert len(out.relations) == 2
    for produced, source in zip(out.relations, result.relations):
        assert produced is not source
        assert produced["created_at"] == source["created_at"]


# --- metrics (spec §Q) -------------------------------------------------------


def test_metrics_vocabulary_is_exact() -> None:
    out = _materialize(_build_result(), (_unrestricted(SELECTED),))
    assert set(out.metrics) == METRIC_KEYS
    for value in out.metrics.values():
        assert isinstance(value, int) and not isinstance(value, bool)
        assert value >= 0


def test_metric_occurrence_vs_unique_semantics() -> None:
    observations = (
        _restricted(
            "7",
            users=[_user(userKey="Admin"), _user(userKey="ADMIN")],
        ),
        _restricted(SELECTED, users=[_user(userKey="admin")]),
    )
    out = _materialize(_build_result(), observations)
    # Two envelopes on the first level, one on the second: 3 occurrences.
    assert out.metrics["observed_user_envelope_occurrences"] == 3
    # All collapse to a single canonical identity.
    assert out.metrics["unique_valid_user_principals"] == 1
    assert out.metrics["effective_users"] == 1


def test_metric_status_counters_are_exact() -> None:
    out = _materialize(_build_result(), (_unrestricted(SELECTED),))
    assert out.metrics["acl_records_total"] == 1
    assert out.metrics["default_deny_records"] == 0
    assert out.metrics["partial_acl_records"] == 0
    assert out.metrics["unavailable_acl_records"] == 0
    assert out.metrics["manual_review_records"] == 0


def test_metric_default_deny_and_manual_review_for_unavailable() -> None:
    out = _materialize(_build_result(), (_unavailable(SELECTED),))
    assert out.metrics["default_deny_records"] == 1
    assert out.metrics["unavailable_acl_records"] == 1
    assert out.metrics["manual_review_records"] == 1
    assert out.metrics["partial_acl_records"] == 0


def test_execution_is_deterministic() -> None:
    result = _build_result()
    observations = (
        _restricted("7", users=[_user(userKey="alpha"), _user(userKey="beta")]),
        _restricted(SELECTED, users=[_user(userKey="alpha")]),
    )
    first = _materialize(result, observations)
    second = _materialize(_build_result(), observations)
    assert first.acl_record == second.acl_record
    assert first.metrics == second.metrics
    assert first.quality_observation == second.quality_observation
    assert first.enriched_chunks == second.enriched_chunks


# --- quality object safety (spec §P) -----------------------------------------


def test_quality_object_exposes_contract_facts_only() -> None:
    out = _materialize(
        _build_result(), (_restricted(SELECTED, users=[_user(userKey="Secret")]),)
    )
    quality = out.quality_observation
    assert quality.default_deny_applied is False
    assert quality.manual_review_required is False
    rendered = repr(quality)
    # No principal source value leaks through the quality object.
    assert "Secret" not in rendered
    assert "secret" not in rendered
    assert "user:secret" not in rendered
