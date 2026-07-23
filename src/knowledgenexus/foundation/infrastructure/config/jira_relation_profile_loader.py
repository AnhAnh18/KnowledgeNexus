from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JiraRelationProfile,
)


class JiraRelationProfileLoadError(ValueError):
    """A sanitized error for an unreadable or malformed Jira relation profile."""


def load_jira_relation_profile(profile_path: Path) -> JiraRelationProfile:
    if not isinstance(profile_path, Path):
        raise TypeError("profile_path expects pathlib.Path")
    try:
        raw_text = profile_path.read_text(encoding="utf-8")
    except OSError:
        raise JiraRelationProfileLoadError(
            "jira relation profile could not be read"
        ) from None
    try:
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        raise JiraRelationProfileLoadError(
            "jira relation profile is invalid YAML"
        ) from None
    if not isinstance(loaded, Mapping) or not all(
        isinstance(key, str) for key in loaded
    ):
        raise JiraRelationProfileLoadError(
            "jira relation profile must be an object"
        )
    expected = {
        "schema_version",
        "extraction_mode",
        "key_pattern",
        "allowed_project_keys",
    }
    if set(loaded) != expected:
        raise JiraRelationProfileLoadError(
            "jira relation profile must contain exactly the active fields"
        )
    projects = loaded["allowed_project_keys"]
    if isinstance(projects, (str, bytes)) or not isinstance(projects, list):
        raise JiraRelationProfileLoadError(
            "allowed_project_keys must be an ordered list"
        )
    try:
        return JiraRelationProfile(
            schema_version=loaded["schema_version"],
            extraction_mode=loaded["extraction_mode"],
            key_pattern=loaded["key_pattern"],
            allowed_project_keys=tuple(projects),
        )
    except (TypeError, ValueError):
        raise JiraRelationProfileLoadError(
            "jira relation profile does not match the active contract"
        ) from None
