from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
    ProjectedPrincipalUnion,
)
from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
    ConfluenceAclMaterializationResult,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    ConfluenceJiraRelationResult,
    copy_json_object,
)
from knowledgenexus.foundation.domain.records.acl_record_builder import (
    ACLRecordBuilder,
)
from knowledgenexus.foundation.domain.rules.acl_principal_projection import (
    project_group_principal,
    project_restriction_principals,
    project_user_principal,
)
from knowledgenexus.foundation.domain.rules.acl_relation_input_validator import (
    AclRelationInputValidator,
)
from knowledgenexus.foundation.domain.rules.acl_restriction_observations import (
    validate_restriction_observations,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationValidationError,
)

_Category = AclMaterializationFailureCategory

_SOURCE_SYSTEM = "confluence"
_DEFAULT_DENY_TAG = "restricted:unresolved"
_DEFAULT_DENY_TAGS = [_DEFAULT_DENY_TAG]

# Space keys are representable as a ``space:`` tag only if the exact source value
# matches the active aclTag space branch; never uppercased, trimmed, or repaired.
_SPACE_KEY_BRANCH = re.compile(r"^[A-Z0-9]+$")

# ``extracted_at`` reuses the exact strict RFC3339 semantics already approved in
# the M6C/M6E application layer (spec §E). Deliberately duplicated here rather
# than refactored into a shared timestamp helper, which is out of M6F-B scope.
_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.[0-9]+)?"
    r"(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _SchemaValidator(Protocol):
    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, object],
        **context: object,
    ) -> None: ...


def _fail(category: AclMaterializationFailureCategory) -> None:
    raise AclMaterializationError(category) from None


def _is_valid_crawler_identity(value: object) -> bool:
    """A non-empty, non-whitespace-only string free of control characters."""
    if not isinstance(value, str) or value == "" or value.strip() == "":
        return False
    # Reject C0 controls (incl. CR/LF/TAB), DEL, and C1 controls so the exact
    # preserved value cannot smuggle line breaks into operator output.
    return not any(ord(char) <= 0x1F or 0x7F <= ord(char) <= 0x9F for char in value)


def _is_rfc3339_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _RFC3339.fullmatch(value)
    if match is None:
        return False
    zone = match.group("zone")
    if zone != "Z":
        hours, minutes = (int(part) for part in zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


@dataclass(frozen=True)
class _ProjectionFacts:
    restriction_observations_total: int
    available_observations: int
    unavailable_observations: int
    restricted_levels: int
    unrestricted_levels: int
    observed_user_envelope_occurrences: int
    observed_group_envelope_occurrences: int
    non_enforceable_user_occurrences: int
    non_enforceable_group_occurrences: int
    unique_valid_user_principals: int
    unique_valid_group_principals: int
    has_unavailable: bool
    union: ProjectedPrincipalUnion
    per_level_user_identities: tuple[frozenset[str], ...]
    per_level_group_identities: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class _AclPolicy:
    is_restricted: bool
    acl_tags: list[str]
    acl_extraction_status: str
    acl_confidence: str
    restriction_inherited: bool | None
    restriction_source_page_ids: list[str] | None
    allowed_users: list[str] | None
    allowed_groups: list[str] | None
    effective_users: int
    effective_groups: int
    user_principals_dropped_by_intersection: int
    group_principals_dropped_by_intersection: int
    reason_codes: tuple[str, ...]


def _compute_projection_facts(
    observations: Sequence[Mapping[str, object]],
) -> _ProjectionFacts:
    """Derive deterministic observation/projection facts (spec §6, §8).

    Occurrence counts include duplicates and casing variants; unique valid
    counts use the M6F-A canonical identity with user/group namespaces kept
    separate. Available restricted observations contribute their safe counts
    even when another observation is unavailable.
    """
    unavailable_observations = 0
    restricted_levels = 0
    unrestricted_levels = 0
    observed_user_envelope_occurrences = 0
    observed_group_envelope_occurrences = 0
    non_enforceable_user_occurrences = 0
    non_enforceable_group_occurrences = 0
    per_level_user_identities: list[frozenset[str]] = []
    per_level_group_identities: list[frozenset[str]] = []

    for observation in observations:
        classification = observation["classification"]
        if classification == "unavailable":
            unavailable_observations += 1
            continue
        if classification == "unrestricted":
            unrestricted_levels += 1
            continue

        restricted_levels += 1
        users = observation["users"]
        groups = observation["groups"]
        assert isinstance(users, list) and isinstance(groups, list)
        observed_user_envelope_occurrences += len(users)
        observed_group_envelope_occurrences += len(groups)

        level_users: set[str] = set()
        for envelope in users:
            principal = project_user_principal(envelope)
            if principal is None:
                non_enforceable_user_occurrences += 1
            else:
                level_users.add(principal.canonical_identity)
        level_groups: set[str] = set()
        for envelope in groups:
            principal = project_group_principal(envelope)
            if principal is None:
                non_enforceable_group_occurrences += 1
            else:
                level_groups.add(principal.canonical_identity)
        per_level_user_identities.append(frozenset(level_users))
        per_level_group_identities.append(frozenset(level_groups))

    union = project_restriction_principals(observations)
    total = len(observations)
    return _ProjectionFacts(
        restriction_observations_total=total,
        available_observations=total - unavailable_observations,
        unavailable_observations=unavailable_observations,
        restricted_levels=restricted_levels,
        unrestricted_levels=unrestricted_levels,
        observed_user_envelope_occurrences=observed_user_envelope_occurrences,
        observed_group_envelope_occurrences=observed_group_envelope_occurrences,
        non_enforceable_user_occurrences=non_enforceable_user_occurrences,
        non_enforceable_group_occurrences=non_enforceable_group_occurrences,
        unique_valid_user_principals=len(union.users),
        unique_valid_group_principals=len(union.groups),
        has_unavailable=unavailable_observations > 0,
        union=union,
        per_level_user_identities=tuple(per_level_user_identities),
        per_level_group_identities=tuple(per_level_group_identities),
    )


def _intersect(per_level: tuple[frozenset[str], ...]) -> frozenset[str]:
    if not per_level:
        return frozenset()
    survivors = set(per_level[0])
    for level in per_level[1:]:
        survivors &= level
    return frozenset(survivors)


def _audit_representations(principals: Sequence[object]) -> list[str]:
    """Exact source representations ordered by canonical identity (spec §4)."""
    return [
        principal.source_representation
        for principal in sorted(
            principals, key=lambda entry: entry.canonical_identity
        )
    ]


def _decide_policy(
    *,
    canonical: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
    facts: _ProjectionFacts,
) -> _AclPolicy:
    # Any unavailable observation → deny-safe unavailable; no intersection is
    # computed and the ACL evidence fields are omitted (spec §5.3, §G).
    if facts.has_unavailable:
        reason_codes = ["restriction_observations_unavailable"]
        if facts.non_enforceable_user_occurrences > 0:
            reason_codes.append("non_enforceable_user_principal")
        if facts.non_enforceable_group_occurrences > 0:
            reason_codes.append("non_enforceable_group_principal")
        return _AclPolicy(
            is_restricted=True,
            acl_tags=list(_DEFAULT_DENY_TAGS),
            acl_extraction_status="unavailable",
            acl_confidence="approximate",
            restriction_inherited=None,
            restriction_source_page_ids=None,
            allowed_users=None,
            allowed_groups=None,
            effective_users=0,
            effective_groups=0,
            user_principals_dropped_by_intersection=0,
            group_principals_dropped_by_intersection=0,
            reason_codes=tuple(reason_codes),
        )

    # Complete chain with zero restricted levels (spec §5.4, §H).
    if facts.restricted_levels == 0:
        space_key = canonical.get("space_key")
        if isinstance(space_key, str) and _SPACE_KEY_BRANCH.fullmatch(space_key):
            return _AclPolicy(
                is_restricted=False,
                acl_tags=[f"space:{space_key}"],
                acl_extraction_status="ok",
                acl_confidence="exact",
                restriction_inherited=False,
                restriction_source_page_ids=[],
                allowed_users=[],
                allowed_groups=[],
                effective_users=0,
                effective_groups=0,
                user_principals_dropped_by_intersection=0,
                group_principals_dropped_by_intersection=0,
                reason_codes=(),
            )
        # Unrepresentable (including null): deny-safe fallback, source
        # unrestricted state preserved (spec §V special case).
        return _AclPolicy(
            is_restricted=False,
            acl_tags=list(_DEFAULT_DENY_TAGS),
            acl_extraction_status="partial",
            acl_confidence="approximate",
            restriction_inherited=False,
            restriction_source_page_ids=[],
            allowed_users=[],
            allowed_groups=[],
            effective_users=0,
            effective_groups=0,
            user_principals_dropped_by_intersection=0,
            group_principals_dropped_by_intersection=0,
            reason_codes=("space_tag_unrepresentable",),
        )

    # Complete chain with at least one restricted level (spec §5.5, §I–§N).
    restricted_source_page_ids = [
        str(observation["source_page_id"])
        for observation in observations
        if observation["classification"] == "restricted"
    ]
    # Inherited iff any restricted observation precedes the selected page (the
    # validated final observation); selected-page-only restriction is False.
    restriction_inherited = any(
        observation["classification"] == "restricted"
        for observation in observations[:-1]
    )

    allowed_users = _audit_representations(facts.union.users)
    allowed_groups = _audit_representations(facts.union.groups)

    effective_user_ids = _intersect(facts.per_level_user_identities)
    effective_group_ids = _intersect(facts.per_level_group_identities)
    union_user_ids = {p.canonical_identity for p in facts.union.users}
    union_group_ids = {p.canonical_identity for p in facts.union.groups}
    user_drops = len(union_user_ids - effective_user_ids)
    group_drops = len(union_group_ids - effective_group_ids)

    effective_tags = sorted(
        {f"user:{identity}" for identity in effective_user_ids}
        | {f"group:{identity}" for identity in effective_group_ids}
    )
    acl_tags = effective_tags if effective_tags else list(_DEFAULT_DENY_TAGS)

    reason_codes: list[str] = []
    if facts.non_enforceable_user_occurrences > 0:
        reason_codes.append("non_enforceable_user_principal")
    if facts.non_enforceable_group_occurrences > 0:
        reason_codes.append("non_enforceable_group_principal")
    if user_drops > 0:
        reason_codes.append("user_principal_dropped_by_intersection")
    if group_drops > 0:
        reason_codes.append("group_principal_dropped_by_intersection")
    if not effective_tags:
        reason_codes.append("empty_effective_intersection")
    partial = bool(reason_codes)

    return _AclPolicy(
        is_restricted=True,
        acl_tags=acl_tags,
        acl_extraction_status="partial" if partial else "ok",
        acl_confidence="approximate" if partial else "exact",
        restriction_inherited=restriction_inherited,
        restriction_source_page_ids=restricted_source_page_ids,
        allowed_users=allowed_users,
        allowed_groups=allowed_groups,
        effective_users=len(effective_user_ids),
        effective_groups=len(effective_group_ids),
        user_principals_dropped_by_intersection=user_drops,
        group_principals_dropped_by_intersection=group_drops,
        reason_codes=tuple(reason_codes),
    )


def _build_quality(
    *, policy: _AclPolicy, facts: _ProjectionFacts
) -> AclQualityObservation:
    return AclQualityObservation(
        restriction_observations_total=facts.restriction_observations_total,
        available_observations=facts.available_observations,
        unavailable_observations=facts.unavailable_observations,
        restricted_levels=facts.restricted_levels,
        unrestricted_levels=facts.unrestricted_levels,
        observed_user_envelope_occurrences=facts.observed_user_envelope_occurrences,
        observed_group_envelope_occurrences=facts.observed_group_envelope_occurrences,
        unique_valid_user_principals=facts.unique_valid_user_principals,
        unique_valid_group_principals=facts.unique_valid_group_principals,
        non_enforceable_user_occurrences=facts.non_enforceable_user_occurrences,
        non_enforceable_group_occurrences=facts.non_enforceable_group_occurrences,
        user_principals_dropped_by_intersection=(
            policy.user_principals_dropped_by_intersection
        ),
        group_principals_dropped_by_intersection=(
            policy.group_principals_dropped_by_intersection
        ),
        effective_users=policy.effective_users,
        effective_groups=policy.effective_groups,
        default_deny_applied=policy.acl_tags == _DEFAULT_DENY_TAGS,
        manual_review_required=policy.acl_extraction_status != "ok",
        reason_codes=policy.reason_codes,
    )


def _build_metrics(
    *,
    policy: _AclPolicy,
    facts: _ProjectionFacts,
    chunks_total: int,
    chunks_acl_changed: int,
) -> dict[str, int]:
    status = policy.acl_extraction_status
    return {
        "acl_records_total": 1,
        "chunks_total": chunks_total,
        "chunks_acl_changed": chunks_acl_changed,
        "restriction_observations_total": facts.restriction_observations_total,
        "available_observations": facts.available_observations,
        "unavailable_observations": facts.unavailable_observations,
        "restricted_levels": facts.restricted_levels,
        "unrestricted_levels": facts.unrestricted_levels,
        "observed_user_envelope_occurrences": (
            facts.observed_user_envelope_occurrences
        ),
        "observed_group_envelope_occurrences": (
            facts.observed_group_envelope_occurrences
        ),
        "unique_valid_user_principals": facts.unique_valid_user_principals,
        "unique_valid_group_principals": facts.unique_valid_group_principals,
        "non_enforceable_user_occurrences": (
            facts.non_enforceable_user_occurrences
        ),
        "non_enforceable_group_occurrences": (
            facts.non_enforceable_group_occurrences
        ),
        "user_principals_dropped_by_intersection": (
            policy.user_principals_dropped_by_intersection
        ),
        "group_principals_dropped_by_intersection": (
            policy.group_principals_dropped_by_intersection
        ),
        "effective_users": policy.effective_users,
        "effective_groups": policy.effective_groups,
        "default_deny_records": int(policy.acl_tags == _DEFAULT_DENY_TAGS),
        "partial_acl_records": int(status == "partial"),
        "unavailable_acl_records": int(status == "unavailable"),
        "manual_review_records": int(status != "ok"),
    }


def _verify_output_invariants(
    *,
    acl_record: Mapping[str, object],
    canonical: Mapping[str, object],
    chunks: Sequence[Mapping[str, object]],
    policy: _AclPolicy,
) -> None:
    acl_tags = policy.acl_tags
    if acl_record.get("acl_id") != canonical.get("acl_id"):
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    if acl_record.get("document_id") != canonical.get("document_id"):
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    if acl_record.get("acl_tags") != acl_tags:
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    if not acl_tags or len(set(acl_tags)) != len(acl_tags):
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    if _DEFAULT_DENY_TAG in acl_tags and acl_tags != _DEFAULT_DENY_TAGS:
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    space_tags = [tag for tag in acl_tags if tag.startswith("space:")]
    if space_tags and acl_tags != space_tags:
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    if policy.is_restricted and space_tags:
        _fail(_Category.ACL_MATERIALIZATION_FAILED)
    for chunk in chunks:
        if chunk.get("acl_tags") != acl_tags:
            _fail(_Category.ACL_MATERIALIZATION_FAILED)


class MaterializeConfluenceAcl:
    """Materialize one page's deny-safe effective ACL and propagate acl_tags.

    Consumes a trusted M6E ``ConfluenceJiraRelationResult`` plus the normalized
    M6B restriction observation chain, an explicit operator ``crawler_identity``
    and ``extracted_at``, and produces exactly one schema-valid ``ACLRecord``
    whose enforced tags are copied onto every trusted chunk. It never calls a
    clock, the network, Confluence, the filesystem, or a group resolver, and
    never mutates its inputs.
    """

    def __init__(self, *, schema_validator: _SchemaValidator) -> None:
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._schema_validator = schema_validator
        self._relation_input_validator = AclRelationInputValidator(
            schema_validator=schema_validator
        )

    def execute(
        self,
        *,
        jira_relation_result: ConfluenceJiraRelationResult,
        restriction_observations: object,
        crawler_identity: object,
        extracted_at: object,
    ) -> ConfluenceAclMaterializationResult:
        # A wrong-typed result is a programmer error, surfaced as ``TypeError``
        # before the sanitized boundary (matching ``AclRelationInputValidator``).
        if not isinstance(jira_relation_result, ConfluenceJiraRelationResult):
            raise TypeError(
                "jira_relation_result expects ConfluenceJiraRelationResult"
            )
        try:
            return self._execute(
                jira_relation_result=jira_relation_result,
                restriction_observations=restriction_observations,
                crawler_identity=crawler_identity,
                extracted_at=extracted_at,
            )
        except AclMaterializationError:
            raise
        except Exception:
            _fail(_Category.ACL_MATERIALIZATION_FAILED)

    def _execute(
        self,
        *,
        jira_relation_result: ConfluenceJiraRelationResult,
        restriction_observations: object,
        crawler_identity: object,
        extracted_at: object,
    ) -> ConfluenceAclMaterializationResult:
        # 1. Full approved M6F-A validation boundary over the entire M6E result
        #    FIRST, so a schema-invalid (even non-JSON) canonical/chunk/relation
        #    yields its precise sanitized category (``canonical_document_invalid``,
        #    ``chunk_record_invalid``, ``m6e_relation_provenance_invalid``) before
        #    any local copy runs. Snapshotting first would mask these as the
        #    generic ``acl_materialization_failed``.
        self._relation_input_validator.validate(jira_relation_result)

        canonical = jira_relation_result.enriched_canonical_document
        input_chunks = jira_relation_result.enriched_chunks
        input_relations = jira_relation_result.relations

        # Snapshot the validated inputs to prove the stage never mutates the
        # trusted M6E result (spec §7, §V). ``deepcopy`` handles any nested value
        # without raising, so the snapshot itself is never a failure point.
        canonical_before = deepcopy(canonical)
        chunks_before = tuple(deepcopy(chunk) for chunk in input_chunks)
        relations_before = tuple(deepcopy(record) for record in input_relations)

        # 2. Validate the M6B observation chain against the canonical page.
        observations = validate_restriction_observations(
            restriction_observations, canonical_page_id=canonical.get("page_id")
        )

        # 3. Explicit operator values (never a clock, never derived).
        if not _is_valid_crawler_identity(crawler_identity):
            _fail(_Category.INVALID_CRAWLER_IDENTITY)
        if not _is_rfc3339_timestamp(extracted_at):
            _fail(_Category.INVALID_EXTRACTED_AT)

        # 4. Deterministic observation/projection facts.
        facts = _compute_projection_facts(observations)

        # 5. Deny-safe effective ACL policy.
        policy = _decide_policy(
            canonical=canonical, observations=observations, facts=facts
        )

        # 6. Build and schema-validate the single ACLRecord.
        acl_record = self._build_acl_record(
            canonical=canonical,
            crawler_identity=crawler_identity,
            extracted_at=extracted_at,
            policy=policy,
        )

        # 7. Ownership-copy every chunk and change only acl_tags.
        enriched_chunks, chunks_acl_changed = self._propagate_chunk_tags(
            input_chunks, policy.acl_tags
        )

        # 8. Deterministic quality + metrics.
        quality = _build_quality(policy=policy, facts=facts)
        metrics = _build_metrics(
            policy=policy,
            facts=facts,
            chunks_total=len(enriched_chunks),
            chunks_acl_changed=chunks_acl_changed,
        )

        # 9. Output invariants and input immutability.
        _verify_output_invariants(
            acl_record=acl_record,
            canonical=canonical,
            chunks=enriched_chunks,
            policy=policy,
        )
        if (
            canonical != canonical_before
            or input_chunks != chunks_before
            or input_relations != relations_before
        ):
            _fail(_Category.ACL_MATERIALIZATION_FAILED)

        return ConfluenceAclMaterializationResult(
            enriched_canonical_document=canonical,
            enriched_chunks=enriched_chunks,
            relations=input_relations,
            acl_record=acl_record,
            quality_observation=quality,
            metrics=metrics,
        )

    def _build_acl_record(
        self,
        *,
        canonical: Mapping[str, object],
        crawler_identity: object,
        extracted_at: object,
        policy: _AclPolicy,
    ) -> dict[str, object]:
        try:
            record = ACLRecordBuilder.build(
                acl_id=canonical.get("acl_id"),
                document_id=canonical.get("document_id"),
                source_system=_SOURCE_SYSTEM,
                is_restricted=policy.is_restricted,
                acl_tags=policy.acl_tags,
                acl_extraction_status=policy.acl_extraction_status,
                extracted_at=extracted_at,
                crawler_identity=crawler_identity,
                acl_confidence=policy.acl_confidence,
                restriction_inherited=policy.restriction_inherited,
                restriction_source_page_ids=policy.restriction_source_page_ids,
                allowed_users=policy.allowed_users,
                allowed_groups=policy.allowed_groups,
            )
        except (TypeError, ValueError):
            _fail(_Category.ACL_MATERIALIZATION_FAILED)
        try:
            self._schema_validator.validate_record("ACLRecord", record)
        except (FoundationValidationError, TypeError, ValueError):
            _fail(_Category.ACL_MATERIALIZATION_FAILED)
        return record

    def _propagate_chunk_tags(
        self,
        chunks: Sequence[Mapping[str, object]],
        acl_tags: list[str],
    ) -> tuple[tuple[dict[str, object], ...], int]:
        enriched: list[dict[str, object]] = []
        changed = 0
        for chunk in chunks:
            copied = copy_json_object(dict(chunk))
            if copied.get("acl_tags") != acl_tags:
                changed += 1
            copied["acl_tags"] = list(acl_tags)
            try:
                self._schema_validator.validate_record("ChunkRecord", copied)
            except (FoundationValidationError, TypeError, ValueError):
                _fail(_Category.CHUNK_RECORD_INVALID)
            enriched.append(copied)
        return tuple(enriched), changed
