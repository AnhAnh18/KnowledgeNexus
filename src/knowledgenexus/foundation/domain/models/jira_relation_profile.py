from __future__ import annotations

import re
from dataclasses import dataclass


JIRA_RELATION_SCHEMA_VERSION = 1
JIRA_EXTRACTION_MODE = "regex_only"
JIRA_KEY_PATTERN = (
    r"(?<![A-Za-z0-9_])"
    r"(?P<key>[A-Z][A-Z0-9_]+-[0-9]+)"
    r"(?![A-Za-z0-9_])"
)
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")


@dataclass(frozen=True, repr=False)
class JiraRelationProfile:
    """Strict immutable configuration for regex-only Jira relation extraction."""

    schema_version: int
    extraction_mode: str
    key_pattern: str
    allowed_project_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("schema_version expects int")
        if self.schema_version != JIRA_RELATION_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        if not isinstance(self.extraction_mode, str):
            raise TypeError("extraction_mode expects str")
        if self.extraction_mode != JIRA_EXTRACTION_MODE:
            raise ValueError("extraction_mode is unsupported")
        if not isinstance(self.key_pattern, str):
            raise TypeError("key_pattern expects str")
        try:
            compiled = re.compile(self.key_pattern)
        except re.error:
            raise ValueError("key_pattern is invalid") from None
        if "key" not in compiled.groupindex:
            raise ValueError("key_pattern requires named group key")
        if self.key_pattern != JIRA_KEY_PATTERN:
            raise ValueError("key_pattern does not match the active contract")

        raw_projects = self.allowed_project_keys
        if isinstance(raw_projects, (str, bytes)):
            raise TypeError("allowed_project_keys expects an ordered collection")
        projects = tuple(raw_projects)
        if not projects:
            raise ValueError("allowed_project_keys must not be empty")
        if not all(isinstance(project, str) for project in projects):
            raise TypeError("allowed_project_keys entries must be strings")
        if any(_PROJECT_KEY.fullmatch(project) is None for project in projects):
            raise ValueError("allowed_project_keys contains an invalid project")
        if len(set(projects)) != len(projects):
            raise ValueError("allowed_project_keys contains duplicates")
        object.__setattr__(self, "allowed_project_keys", projects)
