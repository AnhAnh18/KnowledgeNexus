"""One-page Foundation export contract constants and the profile bundle.

This module is deliberately **not** re-exported from
``knowledgenexus.foundation.domain.models.__init__`` (unlike most domain
models). ``domain/rules/__init__.py`` eagerly imports modules that import
``domain.models.*`` (e.g. ``wiki_structure_parser``), so a domain model that
itself imports a domain *rule* (``TextNormalizationRules``) can form an
order-dependent import cycle if it is also reachable through
``domain/models/__init__.py``. Consumers must import this module directly:
``from knowledgenexus.foundation.domain.models.one_page_export import ...``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import InitVar, dataclass, field
from enum import StrEnum

from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.rules.text_normalization import (
    TextNormalizationRules,
)

# Contract constants (ONE_PAGE_EXPORT_SPEC.md sections 2, 5, 6). These are
# contract constants, never operator-provided values.
ONE_PAGE_DATASET_NAME = "spen_knowledge_poc"
ONE_PAGE_SOURCE_ID = "confluence_svmc_spensrv"
ONE_PAGE_EXPORT_MODE = "full_snapshot"
ONE_PAGE_SCHEMAS_VERSION = "1.0"
ONE_PAGE_CONFIG_CONTRACT_VERSION = "one-page-export-v2"
ONE_PAGE_NORMALIZATION_POLICY_ID = "confluence-table-no-loss-v1"
ONE_PAGE_SPACE_KEY = "SVMC"


# Configuration-failure observability vocabulary locked by spec §10.1.
class OnePageExportStage(StrEnum):
    """Stage values for configuration failure metadata."""

    EMBEDDING_PROFILE_READ = "embedding_profile_read"
    EMBEDDING_PROFILE_DECODE = "embedding_profile_decode"
    EMBEDDING_PROFILE_PARSE = "embedding_profile_parse"
    JIRA_PROFILE_READ = "jira_profile_read"
    JIRA_PROFILE_DECODE = "jira_profile_decode"
    JIRA_PROFILE_PARSE = "jira_profile_parse"
    PROFILE_BUNDLE_CONSTRUCTION = "profile_bundle_construction"
    EXPORT_INPUT_VALIDATION = "export_input_validation"
    GENERATED_AT_VALIDATION = "generated_at_validation"
    DATASET_ROOT_VALIDATION = "dataset_root_validation"
    DATASET_VERSION_GENERATION = "dataset_version_generation"


class OnePageExportCauseFamily(StrEnum):
    """Cause family values for configuration failure metadata."""

    IO_ERROR = "io_error"
    TEXT_DECODE_ERROR = "text_decode_error"
    PROFILE_VALIDATION_ERROR = "profile_validation_error"
    TYPE_ERROR = "type_error"
    VALUE_ERROR = "value_error"
    UNEXPECTED_ERROR = "unexpected_error"


class OnePageExportConfigurationError(Exception):
    """A sanitized one-page export configuration/profile failure.

    Carries typed ``stage`` and ``cause_family`` metadata. ``str(error)``
    returns the category "export_configuration" for backward compatibility.
    """

    def __init__(
        self,
        stage: OnePageExportStage,
        cause_family: OnePageExportCauseFamily,
    ) -> None:
        if not isinstance(stage, OnePageExportStage):
            raise TypeError("stage expects OnePageExportStage")
        if not isinstance(cause_family, OnePageExportCauseFamily):
            raise TypeError("cause_family expects OnePageExportCauseFamily")
        self.stage = stage
        self.cause_family = cause_family
        super().__init__("export_configuration")


def _canonical_config_hash(
    *, embedding_profile_text: str, jira_relation_profile_text: str
) -> str:
    canonical = {
        "contract_version": ONE_PAGE_CONFIG_CONTRACT_VERSION,
        "dataset_name": ONE_PAGE_DATASET_NAME,
        "normalization_policy_id": ONE_PAGE_NORMALIZATION_POLICY_ID,
        "source_id": ONE_PAGE_SOURCE_ID,
        "embedding_profile_text": embedding_profile_text,
        "jira_relation_profile_text": jira_relation_profile_text,
    }
    canonical_json = json.dumps(
        canonical,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, repr=False)
class OnePageExportProfileBundle:
    """Deterministic profile identity for the one-page export (spec §6).

    ``config_hash`` cannot be supplied or overridden by a caller: it is
    ``init=False`` and is computed by ``__post_init__`` from the two
    normalized profile texts, which are ``InitVar`` parameters and are
    therefore never retained on the instance. Constructing with
    ``config_hash=`` raises ``TypeError`` because it is not a constructor
    parameter at all.
    """

    chunking_profile: ChunkingProfile
    jira_relation_profile: JiraRelationProfile
    normalized_embedding_profile_text: InitVar[str]
    normalized_jira_relation_profile_text: InitVar[str]
    config_hash: str = field(init=False)

    def __post_init__(
        self,
        normalized_embedding_profile_text: str,
        normalized_jira_relation_profile_text: str,
    ) -> None:
        if not isinstance(self.chunking_profile, ChunkingProfile):
            raise TypeError("chunking_profile expects ChunkingProfile")
        if not isinstance(self.jira_relation_profile, JiraRelationProfile):
            raise TypeError("jira_relation_profile expects JiraRelationProfile")
        for name, text in (
            (
                "normalized_embedding_profile_text",
                normalized_embedding_profile_text,
            ),
            (
                "normalized_jira_relation_profile_text",
                normalized_jira_relation_profile_text,
            ),
        ):
            if not isinstance(text, str):
                raise TypeError(f"{name} expects str")
            # normalize_text is idempotent, so equality is a valid canonical
            # check without a second normalization pass.
            if TextNormalizationRules.normalize_text(text) != text:
                raise ValueError(f"{name} must already be canonical-normalized")

        digest = _canonical_config_hash(
            embedding_profile_text=normalized_embedding_profile_text,
            jira_relation_profile_text=normalized_jira_relation_profile_text,
        )
        object.__setattr__(self, "config_hash", digest)
