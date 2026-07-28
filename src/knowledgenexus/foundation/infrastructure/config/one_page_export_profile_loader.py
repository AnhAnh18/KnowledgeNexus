from __future__ import annotations

from pathlib import Path

from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportConfigurationError,
    OnePageExportProfileBundle,
)
from knowledgenexus.foundation.domain.rules.text_normalization import (
    TextNormalizationRules,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    ChunkingProfileLoadError,
    parse_chunking_profile_text,
)
from knowledgenexus.foundation.infrastructure.config.jira_relation_profile_loader import (
    JiraRelationProfileLoadError,
    parse_jira_relation_profile_text,
)


def load_one_page_export_profile_bundle(
    *,
    embedding_profile_path: Path,
    jira_relation_profile_path: Path,
) -> OnePageExportProfileBundle:
    """Load the exact profile pair that produces the one-page ``config_hash``.

    Each profile is read exactly once as bytes; the same decoded text is both
    parsed/validated and normalized for the config-hash input, so a
    verify/load mismatch is structurally impossible and no implicit cache is
    used. Every failure is a sanitized ``OnePageExportConfigurationError``.
    """

    if not isinstance(embedding_profile_path, Path):
        raise TypeError("embedding_profile_path expects pathlib.Path")
    if not isinstance(jira_relation_profile_path, Path):
        raise TypeError("jira_relation_profile_path expects pathlib.Path")

    try:
        embedding_text = _read_and_decode(embedding_profile_path)
        chunking_profile = parse_chunking_profile_text(embedding_text)
    except (OSError, ChunkingProfileLoadError, UnicodeDecodeError, TypeError, ValueError):
        raise OnePageExportConfigurationError() from None

    try:
        jira_text = _read_and_decode(jira_relation_profile_path)
        jira_relation_profile = parse_jira_relation_profile_text(jira_text)
    except (
        OSError,
        JiraRelationProfileLoadError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
    ):
        raise OnePageExportConfigurationError() from None

    try:
        return OnePageExportProfileBundle(
            chunking_profile=chunking_profile,
            jira_relation_profile=jira_relation_profile,
            normalized_embedding_profile_text=(
                TextNormalizationRules.normalize_text(embedding_text)
            ),
            normalized_jira_relation_profile_text=(
                TextNormalizationRules.normalize_text(jira_text)
            ),
        )
    except (TypeError, ValueError):
        raise OnePageExportConfigurationError() from None


def _read_and_decode(path: Path) -> str:
    raw_bytes = path.read_bytes()
    return raw_bytes.decode("utf-8")
