from __future__ import annotations

from dataclasses import dataclass

from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    copy_json_object,
)

# Aggregate count fields validated as non-negative, non-bool integers. Kept at
# module scope so it is not mistaken for a dataclass field.
_QUALITY_COUNT_FIELDS = (
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
)

# The seven locked M6F-B reason codes in their deterministic policy order
# (spec §7). ``reason_codes`` may hold only these values, without duplicates and
# in this order, which keeps the quality object free of any free-form text.
_REASON_CODE_ORDER = (
    "restriction_observations_unavailable",
    "non_enforceable_user_principal",
    "non_enforceable_group_principal",
    "user_principal_dropped_by_intersection",
    "group_principal_dropped_by_intersection",
    "empty_effective_intersection",
    "space_tag_unrepresentable",
)
_REASON_CODE_RANK = {code: index for index, code in enumerate(_REASON_CODE_ORDER)}


@dataclass(frozen=True)
class AclQualityObservation:
    """Deterministic, sanitized ACL materialization quality facts (spec §8, §P).

    Every field is a non-sensitive aggregate: counts, deny-safe booleans, and
    reason codes restricted to the locked seven-code §7 vocabulary (unique and
    in policy order). No principal value, page ID, ACL tag value, or source
    content can be stored, so the default ``repr`` cannot leak them.
    """

    restriction_observations_total: int
    available_observations: int
    unavailable_observations: int
    restricted_levels: int
    unrestricted_levels: int
    observed_user_envelope_occurrences: int
    observed_group_envelope_occurrences: int
    unique_valid_user_principals: int
    unique_valid_group_principals: int
    non_enforceable_user_occurrences: int
    non_enforceable_group_occurrences: int
    user_principals_dropped_by_intersection: int
    group_principals_dropped_by_intersection: int
    effective_users: int
    effective_groups: int
    default_deny_applied: bool
    manual_review_required: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in _QUALITY_COUNT_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} expects a non-negative int")
        for name in ("default_deny_applied", "manual_review_required"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} expects bool")
        codes = self.reason_codes
        if isinstance(codes, (str, bytes)):
            raise TypeError("reason_codes expects a collection")
        copied = tuple(codes)
        if not all(isinstance(code, str) for code in copied):
            raise TypeError("reason_codes expects strings")
        # Restrict to the locked §7 vocabulary so no free-form (possibly
        # sensitive) text can ever enter the quality object or its repr.
        if any(code not in _REASON_CODE_RANK for code in copied):
            raise ValueError("reason_codes contains an unrecognized reason code")
        if len(set(copied)) != len(copied):
            raise ValueError("reason_codes must not contain duplicates")
        if list(copied) != sorted(copied, key=_REASON_CODE_RANK.__getitem__):
            raise ValueError("reason_codes must follow the locked policy order")
        object.__setattr__(self, "reason_codes", copied)


@dataclass(frozen=True, repr=False)
class ConfluenceAclMaterializationResult:
    """Frozen, ownership-isolated deny-safe ACL materialization output (spec §U).

    Nested JSON values are recursively copied on construction, mirroring the M6E
    result's ownership model; deep immutability of nested dict/list values is
    deliberately not claimed (spec §5.7). ``repr`` is suppressed so record
    contents (IDs, hashes, principals, page IDs) never render.
    """

    enriched_canonical_document: dict[str, object]
    enriched_chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    acl_record: dict[str, object]
    quality_observation: AclQualityObservation
    metrics: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.enriched_canonical_document, dict):
            raise TypeError("enriched_canonical_document expects dict")
        if isinstance(self.enriched_chunks, (str, bytes)):
            raise TypeError("enriched_chunks expects a collection")
        if isinstance(self.relations, (str, bytes)):
            raise TypeError("relations expects a collection")
        chunks = tuple(self.enriched_chunks)
        relations = tuple(self.relations)
        if not all(isinstance(record, dict) for record in chunks):
            raise TypeError("enriched_chunks expects dict entries")
        if not all(isinstance(record, dict) for record in relations):
            raise TypeError("relations expects dict entries")
        if not isinstance(self.acl_record, dict):
            raise TypeError("acl_record expects dict")
        if not isinstance(self.quality_observation, AclQualityObservation):
            raise TypeError("quality_observation expects AclQualityObservation")
        if not isinstance(self.metrics, dict):
            raise TypeError("metrics expects dict")

        object.__setattr__(
            self,
            "enriched_canonical_document",
            copy_json_object(self.enriched_canonical_document),
        )
        object.__setattr__(
            self,
            "enriched_chunks",
            tuple(copy_json_object(record) for record in chunks),
        )
        object.__setattr__(
            self,
            "relations",
            tuple(copy_json_object(record) for record in relations),
        )
        object.__setattr__(
            self, "acl_record", copy_json_object(self.acl_record)
        )
        object.__setattr__(self, "metrics", copy_json_object(self.metrics))
