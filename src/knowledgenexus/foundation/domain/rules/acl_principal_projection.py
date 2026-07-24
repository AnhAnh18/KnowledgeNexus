from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from knowledgenexus.foundation.domain.models.acl_materialization import (
    GROUP_NAMESPACE,
    USER_NAMESPACE,
    ProjectedPrincipal,
    ProjectedPrincipalUnion,
)

# Any Unicode whitespace, including NBSP, must make an identifier
# non-enforceable so the projected tag stays inside the aclTag ``\S+`` branch.
_WHITESPACE = re.compile(r"\s")


def project_user_principal(
    envelope: Mapping[str, object],
) -> ProjectedPrincipal | None:
    """Project one user envelope to an enforceable principal, or ``None``.

    Enforceable user identity is ``userKey`` only; ``username`` and
    ``accountId`` are never fallback enforcement identities. The source
    representation is the exact ``userKey``, the canonical identity is
    ``userKey.lower()`` (never ``casefold()``), and no value is stripped,
    normalized, or repaired.
    """
    if not isinstance(envelope, Mapping):
        return None
    return _project(USER_NAMESPACE, envelope.get("userKey"))


def project_group_principal(
    envelope: Mapping[str, object],
) -> ProjectedPrincipal | None:
    """Project one group envelope to an enforceable principal, or ``None``.

    Enforceable group identity is the group ``name``; the canonical identity is
    ``name.lower()`` with no stripping, Unicode normalization, or repair.
    """
    if not isinstance(envelope, Mapping):
        return None
    return _project(GROUP_NAMESPACE, envelope.get("name"))


def project_restriction_principals(
    observations: Sequence[Mapping[str, object]],
) -> ProjectedPrincipalUnion:
    """Project the audit union of enforceable principals across restricted levels.

    Precondition: ``observations`` are the output of
    ``validate_restriction_observations()``. This helper is a projection over
    already-validated observations, not a validator; on non-conforming input its
    defensive skips (non-mapping observation, non-restricted level, non-list
    envelope collection) are best effort and must not be relied upon for
    validation. Callers that have untrusted data must validate first.

    Users and groups are kept in separate namespaces (a user and a group with
    the same text remain distinct). Casing variants collapse on the lowercase
    canonical identity, and the earliest exact representation wins, ordered by
    restriction-chain order and then principal-envelope order. This union is the
    audit-evidence building block for M6F-B; it deliberately does not compute
    the effective ACL intersection and does not sort the result.
    """
    users = _OrderedProjection()
    groups = _OrderedProjection()
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        if observation.get("classification") != "restricted":
            continue
        for envelope in _iter_envelopes(observation.get("users")):
            users.add(project_user_principal(envelope))
        for envelope in _iter_envelopes(observation.get("groups")):
            groups.add(project_group_principal(envelope))
    return ProjectedPrincipalUnion(
        users=users.ordered(), groups=groups.ordered()
    )


class _OrderedProjection:
    """Insertion-ordered, casing-collapsed set keyed by canonical identity."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._ordered: list[ProjectedPrincipal] = []

    def add(self, principal: ProjectedPrincipal | None) -> None:
        if principal is None or principal.canonical_identity in self._seen:
            return
        self._seen.add(principal.canonical_identity)
        self._ordered.append(principal)

    def ordered(self) -> tuple[ProjectedPrincipal, ...]:
        return tuple(self._ordered)


def _project(namespace: str, value: object) -> ProjectedPrincipal | None:
    if not isinstance(value, str) or value == "":
        return None
    if _WHITESPACE.search(value) is not None:
        return None
    canonical_identity = value.lower()
    return ProjectedPrincipal(
        namespace=namespace,
        source_representation=value,
        canonical_identity=canonical_identity,
        acl_tag=f"{namespace}:{canonical_identity}",
    )


def _iter_envelopes(value: object) -> tuple[object, ...]:
    if isinstance(value, list):
        return tuple(value)
    return ()
