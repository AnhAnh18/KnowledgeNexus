from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.models import (
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JIRA_RELATION_SCHEMA_VERSION,
    JiraRelationProfile,
)


def _profile(**overrides: object) -> JiraRelationProfile:
    values: dict[str, object] = {
        "schema_version": JIRA_RELATION_SCHEMA_VERSION,
        "extraction_mode": JIRA_EXTRACTION_MODE,
        "key_pattern": JIRA_KEY_PATTERN,
        "allowed_project_keys": ("SVMCSPEN",),
    }
    values.update(overrides)
    return JiraRelationProfile(**values)  # type: ignore[arg-type]


def test_profile_copies_allowlist_to_tuple_and_hides_repr() -> None:
    projects = ["SVMCSPEN", "SPEN_SDK"]
    profile = _profile(allowed_project_keys=projects)
    projects.append("LATE")

    assert profile.allowed_project_keys == ("SVMCSPEN", "SPEN_SDK")
    assert "SVMCSPEN" not in repr(profile)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("extraction_mode", "jira_api"),
        ("key_pattern", "["),
        ("key_pattern", r"[A-Z]+-[0-9]+"),
        (
            "key_pattern",
            r"(?P<key>[A-Z]+-[0-9]+)",
        ),
        ("allowed_project_keys", ()),
        ("allowed_project_keys", ("SVMCSPEN", "SVMCSPEN")),
        ("allowed_project_keys", ("lower",)),
        ("allowed_project_keys", ("S",)),
        ("allowed_project_keys", "SVMCSPEN"),
    ],
)
def test_invalid_profile_is_rejected(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(**{field: value})


def test_active_pattern_rejects_lowercase_adjacent_substrings() -> None:
    import re

    pattern = re.compile(_profile().key_pattern)

    assert pattern.findall("SVMCSPEN-1") == ["SVMCSPEN-1"]
    assert pattern.findall("xSVMCSPEN-1") == []
    assert pattern.findall("SVMCSPEN-1x") == []
    assert pattern.findall("_SVMCSPEN-1") == []
