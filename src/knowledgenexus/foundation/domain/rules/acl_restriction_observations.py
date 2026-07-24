from __future__ import annotations

from collections.abc import Mapping

from knowledgenexus.foundation.domain.models.acl_materialization import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)

_OBSERVATION_FIELDS = frozenset(
    {"source_page_id", "http_status", "classification", "users", "groups"}
)
_CLASSIFICATIONS = frozenset({"unavailable", "unrestricted", "restricted"})
_UNAVAILABLE_STATUSES = frozenset({200, 401, 403, 404})
_USER_ENVELOPE_FIELDS = frozenset({"username", "userKey", "accountId"})

_Category = AclMaterializationFailureCategory


def _fail(category: AclMaterializationFailureCategory) -> None:
    raise AclMaterializationError(category) from None


def validate_restriction_observations(
    observations: object, *, canonical_page_id: object
) -> tuple[dict[str, object], ...]:
    """Validate the exact normalized M6B restriction observation tuple.

    Returns the validated observations in source order. The tuple order is
    authoritative (root ancestor -> descendants -> direct parent -> selected
    page last); the selected page is the final observation and its
    ``source_page_id`` must equal ``canonical_page_id``. Exact ancestry equality
    with the M6A raw page is an M6F-C2 concern and is not checked here. This
    validator mutates nothing and never leaks source values in failures.
    """
    try:
        canonical_page_id = require_confluence_page_id(canonical_page_id)
    except (TypeError, ValueError):
        _fail(_Category.CANONICAL_OBSERVATION_IDENTITY_MISMATCH)

    if isinstance(observations, (str, bytes, Mapping)) or not isinstance(
        observations, (list, tuple)
    ):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    items = tuple(observations)
    if not items:
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    validated: list[dict[str, object]] = []
    seen_page_ids: set[str] = set()
    for observation in items:
        page_id, entry = _validate_one_observation(observation)
        if page_id in seen_page_ids:
            _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
        seen_page_ids.add(page_id)
        validated.append(entry)

    if validated[-1]["source_page_id"] != canonical_page_id:
        _fail(_Category.CANONICAL_OBSERVATION_IDENTITY_MISMATCH)
    return tuple(validated)


def _validate_one_observation(
    observation: object,
) -> tuple[str, dict[str, object]]:
    if not isinstance(observation, Mapping):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    if set(observation.keys()) != _OBSERVATION_FIELDS:
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    try:
        page_id = require_confluence_page_id(observation["source_page_id"])
    except (TypeError, ValueError):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    status = observation["http_status"]
    if isinstance(status, bool) or not isinstance(status, int):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    classification = observation["classification"]
    if not isinstance(classification, str) or classification not in _CLASSIFICATIONS:
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    users = observation["users"]
    groups = observation["groups"]
    if not isinstance(users, list) or not isinstance(groups, list):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)

    _validate_cross_fields(
        classification=classification, status=status, users=users, groups=groups
    )
    for envelope in users:
        _validate_user_envelope(envelope)
    for envelope in groups:
        _validate_group_envelope(envelope)

    # Defensive ownership copy: the validated observation must not alias the
    # caller's nested lists/envelopes, so a later mutation cannot change data
    # after it has crossed the trust boundary (spec §1, §3).
    entry: dict[str, object] = {
        "source_page_id": page_id,
        "http_status": status,
        "classification": classification,
        "users": [dict(envelope) for envelope in users],
        "groups": [dict(envelope) for envelope in groups],
    }
    return page_id, entry


def _validate_cross_fields(
    *,
    classification: str,
    status: int,
    users: list[object],
    groups: list[object],
) -> None:
    if classification == "unavailable":
        if status not in _UNAVAILABLE_STATUSES or users != [] or groups != []:
            _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    elif classification == "unrestricted":
        if status != 200 or users != [] or groups != []:
            _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    else:  # restricted
        if status != 200 or (not users and not groups):
            _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)


def _validate_user_envelope(envelope: object) -> None:
    if not isinstance(envelope, Mapping):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    keys = set(envelope.keys())
    if not keys or not keys <= _USER_ENVELOPE_FIELDS:
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    for value in envelope.values():
        if not isinstance(value, str) or value == "":
            _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)


def _validate_group_envelope(envelope: object) -> None:
    if not isinstance(envelope, Mapping):
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    if set(envelope.keys()) != {"name"}:
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
    value = envelope["name"]
    if not isinstance(value, str) or value == "":
        _fail(_Category.INVALID_RESTRICTION_OBSERVATIONS)
