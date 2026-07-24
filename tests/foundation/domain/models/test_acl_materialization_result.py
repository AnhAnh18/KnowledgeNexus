from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
    ConfluenceAclMaterializationResult,
)


def _quality(**overrides: object) -> AclQualityObservation:
    fields: dict[str, object] = {
        "restriction_observations_total": 0,
        "available_observations": 0,
        "unavailable_observations": 0,
        "restricted_levels": 0,
        "unrestricted_levels": 0,
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


def test_quality_accepts_valid_facts() -> None:
    quality = _quality(
        restricted_levels=2,
        effective_users=1,
        default_deny_applied=True,
        manual_review_required=True,
        reason_codes=["empty_effective_intersection"],
    )
    assert quality.restricted_levels == 2
    # reason_codes is coerced to a tuple.
    assert quality.reason_codes == ("empty_effective_intersection",)


def test_quality_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        _quality(effective_users=-1)


def test_quality_rejects_bool_count() -> None:
    with pytest.raises(ValueError):
        _quality(restricted_levels=True)


def test_quality_rejects_non_bool_flag() -> None:
    with pytest.raises(TypeError):
        _quality(default_deny_applied=1)


def test_quality_rejects_non_string_reason_code() -> None:
    with pytest.raises(TypeError):
        _quality(reason_codes=[123])


def test_quality_rejects_unknown_reason_code() -> None:
    with pytest.raises(ValueError):
        _quality(reason_codes=["totally_made_up"])


def test_quality_rejects_duplicate_reason_codes() -> None:
    with pytest.raises(ValueError):
        _quality(
            reason_codes=[
                "empty_effective_intersection",
                "empty_effective_intersection",
            ]
        )


def test_quality_rejects_out_of_order_reason_codes() -> None:
    with pytest.raises(ValueError):
        _quality(
            reason_codes=[
                "space_tag_unrepresentable",
                "empty_effective_intersection",
            ]
        )


def test_quality_accepts_ordered_vocabulary_subset() -> None:
    quality = _quality(
        reason_codes=[
            "non_enforceable_user_principal",
            "empty_effective_intersection",
        ]
    )
    assert quality.reason_codes == (
        "non_enforceable_user_principal",
        "empty_effective_intersection",
    )


def test_quality_reason_codes_cannot_carry_sensitive_text() -> None:
    # The vocabulary lock means a free-form/sensitive string can never be
    # stored, so it can never surface through the default repr.
    with pytest.raises(ValueError):
        _quality(reason_codes=["user:secret-principal"])


def test_quality_is_frozen() -> None:
    quality = _quality()
    with pytest.raises(Exception):
        quality.effective_users = 5  # type: ignore[misc]


def test_quality_repr_exposes_only_safe_aggregates() -> None:
    rendered = repr(_quality(reason_codes=("space_tag_unrepresentable",)))
    assert "space_tag_unrepresentable" in rendered
    assert "AclQualityObservation" in rendered


def _result(**overrides: object) -> ConfluenceAclMaterializationResult:
    fields: dict[str, object] = {
        "enriched_canonical_document": {"acl_id": "acl:x", "nested": {"k": ["v"]}},
        "enriched_chunks": ({"chunk_id": "c", "acl_tags": ["space:X"]},),
        "relations": ({"relation_id": "r"},),
        "acl_record": {"acl_id": "acl:x", "acl_tags": ["space:X"]},
        "quality_observation": _quality(),
        "metrics": {"acl_records_total": 1},
    }
    fields.update(overrides)
    return ConfluenceAclMaterializationResult(**fields)  # type: ignore[arg-type]


def test_result_recursively_isolates_nested_values() -> None:
    source_doc = {"acl_id": "acl:x", "nested": {"k": ["v"]}}
    source_chunks = ({"chunk_id": "c", "acl_tags": ["space:X"]},)
    result = _result(
        enriched_canonical_document=source_doc, enriched_chunks=source_chunks
    )
    # Mutating the sources must not touch the stored copies.
    source_doc["nested"]["k"].append("late")
    source_chunks[0]["acl_tags"].append("user:injected")
    assert result.enriched_canonical_document["nested"]["k"] == ["v"]
    assert result.enriched_chunks[0]["acl_tags"] == ["space:X"]


def test_result_is_frozen() -> None:
    result = _result()
    with pytest.raises(Exception):
        result.metrics = {}  # type: ignore[misc]


def test_result_repr_does_not_expose_contents() -> None:
    result = _result(
        acl_record={"acl_id": "acl:SENSITIVE", "acl_tags": ["user:secret"]}
    )
    rendered = repr(result)
    assert "SENSITIVE" not in rendered
    assert "user:secret" not in rendered


@pytest.mark.parametrize(
    "field, value",
    [
        ("enriched_canonical_document", ["not", "a", "dict"]),
        ("enriched_chunks", "not-a-collection"),
        ("relations", "not-a-collection"),
        ("acl_record", None),
        ("metrics", ["not-a-dict"]),
    ],
)
def test_result_rejects_wrong_types(field: str, value: object) -> None:
    with pytest.raises(TypeError):
        _result(**{field: value})


def test_result_rejects_non_quality_observation() -> None:
    with pytest.raises(TypeError):
        _result(quality_observation={"not": "quality"})
