from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models import (
    AclMaterializationError,
    AclMaterializationFailureCategory,
)
from knowledgenexus.foundation.domain.rules.acl_restriction_observations import (
    validate_restriction_observations,
)

SELECTED = "1000"
_Category = AclMaterializationFailureCategory


def _observation(
    page_id: str,
    *,
    status: int = 200,
    classification: str = "unrestricted",
    users=None,
    groups=None,
) -> dict[str, object]:
    return {
        "source_page_id": page_id,
        "http_status": status,
        "classification": classification,
        "users": list(users or []),
        "groups": list(groups or []),
    }


def _selected(**kwargs) -> dict[str, object]:
    return _observation(SELECTED, **kwargs)


def _chain(*leading: dict[str, object], selected: dict[str, object] | None = None):
    return (*leading, selected or _selected())


def _expect(category: _Category, observations, *, page_id: str = SELECTED):
    with pytest.raises(AclMaterializationError) as exc:
        validate_restriction_observations(observations, canonical_page_id=page_id)
    assert exc.value.category is category
    return exc.value


def test_valid_chain_returns_ordered_five_field_observations() -> None:
    chain = _chain(
        _observation("7", status=404, classification="unavailable"),
        _observation("8", status=200, classification="unrestricted"),
        selected=_selected(
            status=200, classification="restricted", users=[{"userKey": "ADMIN"}]
        ),
    )

    result = validate_restriction_observations(chain, canonical_page_id=SELECTED)

    assert result == chain
    assert [entry["source_page_id"] for entry in result] == ["7", "8", SELECTED]


def test_unknown_field_is_rejected() -> None:
    bad = _selected()
    bad["availability"] = "unknown"
    _expect(_Category.INVALID_RESTRICTION_OBSERVATIONS, (bad,))


def test_empty_chain_is_rejected() -> None:
    _expect(_Category.INVALID_RESTRICTION_OBSERVATIONS, ())


@pytest.mark.parametrize("page_id", ["", "abc", "10 0", "-1", "1.0"])
def test_invalid_source_page_ids_are_rejected(page_id: str) -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_observation(page_id), _selected()),
    )


def test_duplicate_page_ids_are_rejected() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_observation("7"), _observation("7"), _selected()),
    )


def test_selected_page_must_be_last() -> None:
    _expect(
        _Category.CANONICAL_OBSERVATION_IDENTITY_MISMATCH,
        (_selected(), _observation("8")),
    )


def test_selected_identity_must_match_canonical_page() -> None:
    _expect(
        _Category.CANONICAL_OBSERVATION_IDENTITY_MISMATCH,
        (_observation("7"), _observation("999")),
    )


def test_bool_http_status_is_rejected() -> None:
    bad = _selected()
    bad["http_status"] = True
    _expect(_Category.INVALID_RESTRICTION_OBSERVATIONS, (bad,))


def test_invalid_classification_is_rejected() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="secret"),),
    )


@pytest.mark.parametrize(
    "classification",
    [[], {}, ["restricted"], {"restricted": True}, 5, None],
    ids=["list", "dict", "list-value", "dict-value", "int", "none"],
)
def test_non_string_classification_fails_closed_without_raw_typeerror(
    classification: object,
) -> None:
    bad = _selected()
    bad["classification"] = classification
    error = _expect(_Category.INVALID_RESTRICTION_OBSERVATIONS, (bad,))
    assert str(error) == "invalid_restriction_observations"


def test_validated_observations_do_not_alias_caller_nested_data() -> None:
    envelope = {"userKey": "Alice"}
    users = [envelope]
    groups: list[dict[str, object]] = []
    observation = {
        "source_page_id": SELECTED,
        "http_status": 200,
        "classification": "restricted",
        "users": users,
        "groups": groups,
    }

    result = validate_restriction_observations(
        (observation,), canonical_page_id=SELECTED
    )

    # Mutating the caller's originals after validation must not change the
    # data that has already crossed the trust boundary.
    envelope["userKey"] = "Mallory"
    users.append({"userKey": "Eve"})
    groups.append({"name": "late-group"})

    assert result[0]["users"] == [{"userKey": "Alice"}]
    assert result[0]["groups"] == []


@pytest.mark.parametrize("status", [200, 401, 403, 404])
def test_unavailable_accepts_its_supported_statuses(status: int) -> None:
    chain = _chain(
        _observation("7", status=status, classification="unavailable"),
    )

    result = validate_restriction_observations(chain, canonical_page_id=SELECTED)

    assert result[0]["classification"] == "unavailable"


def test_unavailable_with_unsupported_status_is_rejected() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_observation("7", status=500, classification="unavailable"), _selected()),
    )


def test_unavailable_with_principals_is_rejected() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (
            _observation(
                "7",
                status=200,
                classification="unavailable",
                users=[{"userKey": "x"}],
            ),
            _selected(),
        ),
    )


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_unrestricted_requires_status_200(status: int) -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(status=status, classification="unrestricted"),),
    )


def test_unrestricted_requires_empty_principals() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="unrestricted", groups=[{"name": "g"}]),),
    )


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_restricted_requires_status_200(status: int) -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(status=status, classification="restricted", users=[{"userKey": "x"}]),),
    )


def test_restricted_requires_at_least_one_envelope() -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="restricted"),),
    )


def test_restricted_accepts_group_only() -> None:
    result = validate_restriction_observations(
        (_selected(classification="restricted", groups=[{"name": "Dev"}]),),
        canonical_page_id=SELECTED,
    )

    assert result[0]["groups"] == [{"name": "Dev"}]


@pytest.mark.parametrize(
    "user",
    [
        {"unknown": "x"},
        {"userKey": ""},
        {"userKey": 5},
        {},
        {"userKey": "k", "unexpected": "v"},
    ],
)
def test_malformed_user_envelopes_are_rejected(user: dict[str, object]) -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="restricted", users=[user]),),
    )


@pytest.mark.parametrize(
    "group",
    [{"name": ""}, {"name": 123}, {"name": "g", "extra": "y"}, {"label": "g"}, {}],
)
def test_malformed_group_envelopes_are_rejected(group: dict[str, object]) -> None:
    _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="restricted", groups=[group]),),
    )


def test_valid_user_envelope_allows_any_subset_of_allowed_fields() -> None:
    result = validate_restriction_observations(
        (
            _selected(
                classification="restricted",
                users=[
                    {"username": "u", "userKey": "k", "accountId": "a"},
                    {"userKey": "only-key"},
                ],
            ),
        ),
        canonical_page_id=SELECTED,
    )

    assert result[0]["users"][0] == {"username": "u", "userKey": "k", "accountId": "a"}


def test_non_sequence_observations_are_rejected() -> None:
    _expect(_Category.INVALID_RESTRICTION_OBSERVATIONS, {"source_page_id": SELECTED})


def test_failure_message_is_only_the_category() -> None:
    error = _expect(
        _Category.INVALID_RESTRICTION_OBSERVATIONS,
        (_selected(classification="restricted", users=[{"userKey": "SECRET-USER"}], groups=[{"name": "x"}], status=403),),
    )
    assert "SECRET-USER" not in str(error)
    assert str(error) == "invalid_restriction_observations"
