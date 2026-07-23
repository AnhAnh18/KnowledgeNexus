from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models import JIRA_KEY_PATTERN
from knowledgenexus.foundation.infrastructure.config import (
    JiraRelationProfileLoadError,
    load_jira_relation_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"


def test_loads_exact_active_profile() -> None:
    profile = load_jira_relation_profile(PROFILE_PATH)

    assert profile.schema_version == 1
    assert profile.extraction_mode == "regex_only"
    assert profile.key_pattern == JIRA_KEY_PATTERN
    assert profile.allowed_project_keys == ("SVMCSPEN",)


@pytest.mark.parametrize(
    "body",
    [
        "[]",
        "schema_version: 1\n",
        (
            "schema_version: 1\nextraction_mode: regex_only\n"
            "key_pattern: '['\nallowed_project_keys: [SVMCSPEN]\n"
        ),
        (
            "schema_version: 1\nextraction_mode: regex_only\n"
            "key_pattern: '(?P<key>[A-Z]+-[0-9]+)'\n"
            "allowed_project_keys: [SVMCSPEN]\n"
        ),
        (
            "schema_version: 1\nextraction_mode: regex_only\n"
            f"key_pattern: '{JIRA_KEY_PATTERN}'\n"
            "allowed_project_keys: [SVMCSPEN, SVMCSPEN]\n"
        ),
        (
            "schema_version: 1\nextraction_mode: jira_api\n"
            f"key_pattern: '{JIRA_KEY_PATTERN}'\n"
            "allowed_project_keys: [SVMCSPEN]\n"
        ),
    ],
)
def test_rejects_malformed_or_non_contract_profile(
    tmp_path: Path,
    body: str,
) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(body, encoding="utf-8")

    with pytest.raises(JiraRelationProfileLoadError) as exc_info:
        load_jira_relation_profile(profile_path)

    assert str(profile_path) not in str(exc_info.value)
    assert "SVMCSPEN" not in str(exc_info.value)


def test_missing_profile_has_sanitized_error(tmp_path: Path) -> None:
    missing = tmp_path / "SENSITIVE-profile.yaml"

    with pytest.raises(JiraRelationProfileLoadError) as exc_info:
        load_jira_relation_profile(missing)

    assert "SENSITIVE" not in str(exc_info.value)
