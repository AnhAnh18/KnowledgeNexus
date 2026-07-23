from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# Any Unicode whitespace (including NBSP) would push a projected tag outside the
# aclTag ``\S+`` branch, so an enforceable identity must contain none.
_WHITESPACE = re.compile(r"\s")


class AclMaterializationFailureCategory(StrEnum):
    """Sanitized M6F failures safe for operator output.

    Only the categories raised by M6F-A validators/models are listed here. The
    complete later-stage vocabulary (adding ``invalid_crawler_identity`` and
    ``invalid_extracted_at`` for M6F-B ``ACLRecord`` construction) is locked in
    ``contracts/foundation/ACL_MATERIALIZATION_SPEC.md`` §12.
    """

    CANONICAL_DOCUMENT_INVALID = "canonical_document_invalid"
    CHUNK_RECORD_INVALID = "chunk_record_invalid"
    CANONICAL_CHUNK_IDENTITY_MISMATCH = "canonical_chunk_identity_mismatch"
    ACL_STAGE_INPUT_NOT_PRISTINE = "acl_stage_input_not_pristine"
    M6E_RELATION_PROVENANCE_INVALID = "m6e_relation_provenance_invalid"
    M6E_RESULT_PROVENANCE_INVALID = "m6e_result_provenance_invalid"
    INVALID_RESTRICTION_OBSERVATIONS = "invalid_restriction_observations"
    CANONICAL_OBSERVATION_IDENTITY_MISMATCH = (
        "canonical_observation_identity_mismatch"
    )
    ACL_MATERIALIZATION_FAILED = "acl_materialization_failed"


class AclMaterializationError(Exception):
    """An M6F failure whose message contains only a stable category."""

    def __init__(self, category: AclMaterializationFailureCategory) -> None:
        if not isinstance(category, AclMaterializationFailureCategory):
            raise TypeError(
                "category expects AclMaterializationFailureCategory"
            )
        self.category = category
        super().__init__(category.value)


# Enforceable principal namespaces. A user and a group with the same textual
# value remain different principals (spec §4).
USER_NAMESPACE = "user"
GROUP_NAMESPACE = "group"


@dataclass(frozen=True, repr=False)
class ProjectedPrincipal:
    """One enforceable principal projected from a restriction envelope.

    ``source_representation`` is the exact ``userKey``/group ``name`` observed,
    ``canonical_identity`` is its ``lower()`` form, and ``acl_tag`` is the
    resulting ``user:``/``group:`` tag. All three carry principal identity and
    are hidden from ``repr``; only the non-sensitive namespace is shown.
    """

    namespace: str
    source_representation: str
    canonical_identity: str
    acl_tag: str

    def __post_init__(self) -> None:
        if self.namespace not in (USER_NAMESPACE, GROUP_NAMESPACE):
            raise ValueError("namespace expects 'user' or 'group'")
        for field_name in (
            "source_representation",
            "canonical_identity",
            "acl_tag",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{field_name} expects a non-empty string")
        # A projected principal must not be able to hold self-inconsistent
        # state, because M6F-B consumes these as enforcement building blocks.
        if _WHITESPACE.search(self.source_representation) is not None:
            raise ValueError("source_representation must not contain whitespace")
        if self.canonical_identity != self.source_representation.lower():
            raise ValueError(
                "canonical_identity must equal source_representation.lower()"
            )
        if self.acl_tag != f"{self.namespace}:{self.canonical_identity}":
            raise ValueError(
                "acl_tag must equal '<namespace>:<canonical_identity>'"
            )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(namespace={self.namespace!r})"


@dataclass(frozen=True, repr=False)
class ProjectedPrincipalUnion:
    """The ordered, casing-collapsed audit union of enforceable principals.

    Users and groups are kept in separate namespaces and in earliest-occurrence
    order. This is the audit-union building block for M6F-B; it deliberately
    does not compute the effective ACL intersection. ``repr`` exposes only
    counts, never principal identities.
    """

    users: tuple[ProjectedPrincipal, ...]
    groups: tuple[ProjectedPrincipal, ...]

    def __post_init__(self) -> None:
        for field_name, expected_namespace in (
            ("users", USER_NAMESPACE),
            ("groups", GROUP_NAMESPACE),
        ):
            value = getattr(self, field_name)
            if isinstance(value, (str, bytes)):
                raise TypeError(f"{field_name} expects a collection")
            copied = tuple(value)
            if not all(
                isinstance(entry, ProjectedPrincipal) for entry in copied
            ):
                raise TypeError(
                    f"{field_name} expects ProjectedPrincipal entries"
                )
            if any(entry.namespace != expected_namespace for entry in copied):
                raise ValueError(
                    f"{field_name} expects only '{expected_namespace}' principals"
                )
            identities = [entry.canonical_identity for entry in copied]
            if len(set(identities)) != len(identities):
                raise ValueError(
                    f"{field_name} must not contain duplicate canonical identities"
                )
            object.__setattr__(self, field_name, copied)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(users={len(self.users)}, groups={len(self.groups)})"
        )
