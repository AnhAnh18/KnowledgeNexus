from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules.acl_principal_projection import (
    project_group_principal,
    project_restriction_principals,
    project_user_principal,
)

# Non-ASCII probes are built from code points so no literal character can be
# silently normalized in the source file.
_SHARP_S = chr(0x00DF)  # "ß": lower() keeps it, casefold() would expand to "ss"


def _restricted(page_id: str, *, users=None, groups=None) -> dict[str, object]:
    return {
        "source_page_id": page_id,
        "http_status": 200,
        "classification": "restricted",
        "users": list(users or []),
        "groups": list(groups or []),
    }


def test_userkey_is_the_enforceable_user_identity() -> None:
    principal = project_user_principal(
        {"userKey": "ADMIN", "username": "ignored", "accountId": "ignored"}
    )

    assert principal is not None
    assert principal.namespace == "user"
    assert principal.source_representation == "ADMIN"
    assert principal.canonical_identity == "admin"
    assert principal.acl_tag == "user:admin"


def test_username_only_is_non_enforceable() -> None:
    assert project_user_principal({"username": "someone"}) is None


def test_account_id_only_is_non_enforceable() -> None:
    assert project_user_principal({"accountId": "5b10ac"}) is None


def test_username_and_account_id_never_become_fallback_identities() -> None:
    assert project_user_principal({"username": "u", "accountId": "a"}) is None


def test_group_name_is_the_enforceable_group_identity() -> None:
    principal = project_group_principal({"name": "Platform-Team"})

    assert principal is not None
    assert principal.namespace == "group"
    assert principal.source_representation == "Platform-Team"
    assert principal.canonical_identity == "platform-team"
    assert principal.acl_tag == "group:platform-team"


def test_lowercase_uses_lower_not_casefold() -> None:
    source = "ma" + _SHARP_S
    principal = project_user_principal({"userKey": source})

    assert principal is not None
    assert principal.source_representation == source
    # lower() leaves the sharp-s intact; casefold() would have produced "mass".
    assert principal.canonical_identity == source
    assert principal.canonical_identity != "mass"


@pytest.mark.parametrize(
    "code",
    [0x20, 0x09, 0x0A, 0x00A0, 0x2028, 0x3000],
    ids=["space", "tab", "newline", "nbsp", "line-sep", "ideographic"],
)
def test_unicode_whitespace_including_nbsp_is_non_enforceable(code: int) -> None:
    value = "a" + chr(code) + "b"
    assert project_user_principal({"userKey": value}) is None
    assert project_group_principal({"name": value}) is None


def test_values_are_not_trimmed_or_repaired() -> None:
    principal = project_user_principal({"userKey": "a.b--c"})

    assert principal is not None
    assert principal.source_representation == "a.b--c"
    assert principal.canonical_identity == "a.b--c"


def test_empty_or_missing_key_is_non_enforceable() -> None:
    assert project_user_principal({"userKey": ""}) is None
    assert project_user_principal({}) is None
    assert project_group_principal({"name": ""}) is None


def test_casing_collision_within_one_level_keeps_earliest_representation() -> None:
    union = project_restriction_principals(
        [_restricted("1000", users=[{"userKey": "Admin"}, {"userKey": "ADMIN"}])]
    )

    assert len(union.users) == 1
    assert union.users[0].source_representation == "Admin"
    assert union.users[0].canonical_identity == "admin"


def test_casing_collision_across_levels_keeps_earliest_chain_representation() -> None:
    union = project_restriction_principals(
        [
            _restricted("7", users=[{"userKey": "Admin"}]),
            _restricted("1000", users=[{"userKey": "ADMIN"}]),
        ]
    )

    assert len(union.users) == 1
    assert union.users[0].source_representation == "Admin"


def test_user_and_group_with_same_text_remain_separate_namespaces() -> None:
    union = project_restriction_principals(
        [_restricted("1000", users=[{"userKey": "team"}], groups=[{"name": "team"}])]
    )

    assert [p.acl_tag for p in union.users] == ["user:team"]
    assert [p.acl_tag for p in union.groups] == ["group:team"]


def test_only_restricted_levels_and_enforceable_principals_contribute() -> None:
    observations = [
        {
            "source_page_id": "5",
            "http_status": 404,
            "classification": "unavailable",
            "users": [],
            "groups": [],
        },
        {
            "source_page_id": "6",
            "http_status": 200,
            "classification": "unrestricted",
            "users": [],
            "groups": [],
        },
        _restricted(
            "1000",
            users=[{"username": "no-key"}, {"userKey": "Real"}],
            groups=[{"name": "Group-A"}],
        ),
    ]

    union = project_restriction_principals(observations)

    assert [p.acl_tag for p in union.users] == ["user:real"]
    assert [p.acl_tag for p in union.groups] == ["group:group-a"]


def test_projection_does_not_sort_the_union() -> None:
    union = project_restriction_principals(
        [
            _restricted(
                "1000",
                users=[{"userKey": "zeta"}, {"userKey": "alpha"}],
                groups=[{"name": "zulu"}, {"name": "alpha"}],
            )
        ]
    )

    assert [p.canonical_identity for p in union.users] == ["zeta", "alpha"]
    assert [p.canonical_identity for p in union.groups] == ["zulu", "alpha"]
