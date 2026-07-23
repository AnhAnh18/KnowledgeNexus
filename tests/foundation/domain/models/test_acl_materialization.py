from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    ProjectedPrincipal,
    ProjectedPrincipalUnion,
)


def test_error_message_is_only_the_stable_category() -> None:
    error = AclMaterializationError(
        AclMaterializationFailureCategory.M6E_RELATION_PROVENANCE_INVALID
    )

    assert error.category is (
        AclMaterializationFailureCategory.M6E_RELATION_PROVENANCE_INVALID
    )
    assert str(error) == "m6e_relation_provenance_invalid"


def test_error_rejects_non_category() -> None:
    with pytest.raises(TypeError):
        AclMaterializationError("m6e_relation_provenance_invalid")  # type: ignore[arg-type]


def test_failure_vocabulary_is_the_m6f_a_subset() -> None:
    assert {category.value for category in AclMaterializationFailureCategory} == {
        "canonical_document_invalid",
        "chunk_record_invalid",
        "canonical_chunk_identity_mismatch",
        "acl_stage_input_not_pristine",
        "m6e_relation_provenance_invalid",
        "m6e_result_provenance_invalid",
        "invalid_restriction_observations",
        "canonical_observation_identity_mismatch",
        "acl_materialization_failed",
    }


def test_projected_principal_repr_hides_source_values() -> None:
    principal = ProjectedPrincipal(
        namespace="user",
        source_representation="SENSITIVE-Key",
        canonical_identity="sensitive-key",
        acl_tag="user:sensitive-key",
    )

    rendered = repr(principal)
    assert "SENSITIVE" not in rendered
    assert "sensitive-key" not in rendered
    assert rendered == "ProjectedPrincipal(namespace='user')"


def test_projected_principal_rejects_bad_namespace_and_empty_values() -> None:
    with pytest.raises(ValueError):
        ProjectedPrincipal(
            namespace="service",
            source_representation="k",
            canonical_identity="k",
            acl_tag="user:k",
        )
    with pytest.raises(ValueError):
        ProjectedPrincipal(
            namespace="user",
            source_representation="",
            canonical_identity="k",
            acl_tag="user:k",
        )


def test_projected_principal_rejects_self_inconsistent_state() -> None:
    # canonical_identity is not source_representation.lower()
    with pytest.raises(ValueError):
        ProjectedPrincipal(
            namespace="user",
            source_representation="Alice",
            canonical_identity="bob",
            acl_tag="user:alice",
        )
    # acl_tag is not "<namespace>:<canonical_identity>"
    with pytest.raises(ValueError):
        ProjectedPrincipal(
            namespace="user",
            source_representation="Alice",
            canonical_identity="alice",
            acl_tag="group:admin",
        )
    # identity carries whitespace (would escape the aclTag \S+ branch)
    with pytest.raises(ValueError):
        ProjectedPrincipal(
            namespace="user",
            source_representation="a b",
            canonical_identity="a b",
            acl_tag="user:a b",
        )


def test_projected_principal_union_enforces_namespace_partitioning() -> None:
    group = ProjectedPrincipal(
        namespace="group",
        source_representation="admins",
        canonical_identity="admins",
        acl_tag="group:admins",
    )
    with pytest.raises(ValueError):
        ProjectedPrincipalUnion(users=(group,), groups=())

    user = ProjectedPrincipal(
        namespace="user",
        source_representation="Alice",
        canonical_identity="alice",
        acl_tag="user:alice",
    )
    with pytest.raises(ValueError):
        ProjectedPrincipalUnion(users=(), groups=(user,))


def test_projected_principal_union_rejects_duplicate_canonical_identities() -> None:
    first = ProjectedPrincipal(
        namespace="user",
        source_representation="Alice",
        canonical_identity="alice",
        acl_tag="user:alice",
    )
    second = ProjectedPrincipal(
        namespace="user",
        source_representation="ALICE",
        canonical_identity="alice",
        acl_tag="user:alice",
    )
    with pytest.raises(ValueError):
        ProjectedPrincipalUnion(users=(first, second), groups=())


def test_projected_principal_union_repr_exposes_only_counts() -> None:
    user = ProjectedPrincipal(
        namespace="user",
        source_representation="SENSITIVE",
        canonical_identity="sensitive",
        acl_tag="user:sensitive",
    )
    union = ProjectedPrincipalUnion(users=(user,), groups=())

    rendered = repr(union)
    assert "SENSITIVE" not in rendered
    assert rendered == "ProjectedPrincipalUnion(users=1, groups=0)"


def test_projected_principal_union_copies_and_type_checks_entries() -> None:
    user = ProjectedPrincipal(
        namespace="user",
        source_representation="K",
        canonical_identity="k",
        acl_tag="user:k",
    )
    source = [user]
    union = ProjectedPrincipalUnion(users=source, groups=())
    source.append(user)

    assert union.users == (user,)

    with pytest.raises(TypeError):
        ProjectedPrincipalUnion(users=({"not": "principal"},), groups=())  # type: ignore[arg-type]
