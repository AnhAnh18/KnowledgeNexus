from __future__ import annotations

from pathlib import Path

from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportCauseFamily,
    OnePageExportConfigurationError,
    OnePageExportStage,
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
    used. Every failure is a sanitized ``OnePageExportConfigurationError`` with
    typed ``stage`` and ``cause_family`` metadata (spec §10.1).
    """

    if not isinstance(embedding_profile_path, Path):
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EXPORT_INPUT_VALIDATION,
            cause_family=OnePageExportCauseFamily.TYPE_ERROR,
        )
    if not isinstance(jira_relation_profile_path, Path):
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EXPORT_INPUT_VALIDATION,
            cause_family=OnePageExportCauseFamily.TYPE_ERROR,
        )

    # Stage 1-3: embedding profile read/decode/parse
    try:
        embedding_text = _read_and_decode(embedding_profile_path)
    except OSError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_READ,
            cause_family=OnePageExportCauseFamily.IO_ERROR,
        ) from None
    except UnicodeDecodeError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_DECODE,
            cause_family=OnePageExportCauseFamily.TEXT_DECODE_ERROR,
        ) from None

    try:
        chunking_profile = parse_chunking_profile_text(embedding_text)
    except ChunkingProfileLoadError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.PROFILE_VALIDATION_ERROR,
        ) from None
    except TypeError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.TYPE_ERROR,
        ) from None
    except ValueError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.VALUE_ERROR,
        ) from None

    # Stage 4-6: jira profile read/decode/parse
    try:
        jira_text = _read_and_decode(jira_relation_profile_path)
    except OSError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.JIRA_PROFILE_READ,
            cause_family=OnePageExportCauseFamily.IO_ERROR,
        ) from None
    except UnicodeDecodeError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.JIRA_PROFILE_DECODE,
            cause_family=OnePageExportCauseFamily.TEXT_DECODE_ERROR,
        ) from None

    try:
        jira_relation_profile = parse_jira_relation_profile_text(jira_text)
    except JiraRelationProfileLoadError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.JIRA_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.PROFILE_VALIDATION_ERROR,
        ) from None
    except TypeError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.JIRA_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.TYPE_ERROR,
        ) from None
    except ValueError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.JIRA_PROFILE_PARSE,
            cause_family=OnePageExportCauseFamily.VALUE_ERROR,
        ) from None

    # Stage 7: profile_bundle_construction
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
    except TypeError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.PROFILE_BUNDLE_CONSTRUCTION,
            cause_family=OnePageExportCauseFamily.TYPE_ERROR,
        ) from None
    except ValueError:
        raise OnePageExportConfigurationError(
            stage=OnePageExportStage.PROFILE_BUNDLE_CONSTRUCTION,
            cause_family=OnePageExportCauseFamily.VALUE_ERROR,
        ) from None


def _read_and_decode(path: Path) -> str:
    raw_bytes = path.read_bytes()
    return raw_bytes.decode("utf-8")
