from __future__ import annotations

from dataclasses import dataclass

from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    ConfluenceAclMaterializationResult,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    ConfluenceJiraRelationResult,
    copy_json_object,
)

_RESTRICTION_ANCESTRY_CATEGORY = "restriction_ancestry"
_ACCEPTANCE_CATEGORY = "acceptance"


class ConfluenceAclRestrictionAncestryError(Exception):
    """A sanitized pre-materialization restriction observation/ancestry failure.

    Raised for an invalid, mismatched, or non-ancestry-matching restriction
    observation chain before ``MaterializeConfluenceAcl`` ever runs. ``str()``
    carries only the stable category, never a page ID, principal, or path.
    """

    def __init__(self) -> None:
        super().__init__(_RESTRICTION_ANCESTRY_CATEGORY)


class ConfluenceAclCompositionAcceptanceError(Exception):
    """A sanitized post-composition invariant or cross-binding failure.

    Raised when the composed M6E/M6F stages do not agree with each other (the
    composition result is a trust boundary, not a container) or when an
    internal immutability check fails. ``str()`` carries only the stable
    category.
    """

    def __init__(self) -> None:
        super().__init__(_ACCEPTANCE_CATEGORY)


@dataclass(frozen=True, repr=False)
class ConfluenceAclCompositionResult:
    """Frozen, ownership-isolated one-page M6A-through-M6F composition output.

    ``validated_restriction_observations`` is the ordered ownership-isolated
    tuple of validated restriction observations bound to the trusted page, kept
    alongside the two composed stage results so a caller (or the CLI's
    deterministic-repeat check) can compare a full run without re-deriving it.
    ``repr`` is suppressed so record contents never render.
    """

    jira_relation_result: ConfluenceJiraRelationResult
    acl_materialization_result: ConfluenceAclMaterializationResult
    validated_restriction_observations: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.jira_relation_result, ConfluenceJiraRelationResult):
            raise TypeError(
                "jira_relation_result expects ConfluenceJiraRelationResult"
            )
        if not isinstance(
            self.acl_materialization_result, ConfluenceAclMaterializationResult
        ):
            raise TypeError(
                "acl_materialization_result expects "
                "ConfluenceAclMaterializationResult"
            )
        if isinstance(self.validated_restriction_observations, (str, bytes)):
            raise TypeError(
                "validated_restriction_observations expects a collection"
            )
        observations = tuple(self.validated_restriction_observations)
        if not all(isinstance(entry, dict) for entry in observations):
            raise TypeError(
                "validated_restriction_observations expects dict entries"
            )
        object.__setattr__(
            self,
            "validated_restriction_observations",
            tuple(copy_json_object(entry) for entry in observations),
        )
