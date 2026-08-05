from __future__ import annotations

from dataclasses import replace

import pytest

from knowledgenexus.foundation.domain.models.chunking_profile import (
    ChunkingProfile,
    TokenizerAsset,
)
from knowledgenexus.foundation.domain.models.jira_relation_profile import (
    JIRA_EXTRACTION_MODE,
    JIRA_KEY_PATTERN,
    JiraRelationProfile,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_CONFIG_CONTRACT_VERSION,
    ONE_PAGE_DATASET_NAME,
    ONE_PAGE_EXPORT_MODE,
    ONE_PAGE_NORMALIZATION_POLICY_ID,
    ONE_PAGE_SCHEMAS_VERSION,
    ONE_PAGE_SOURCE_ID,
    ONE_PAGE_SPACE_KEY,
    OnePageExportCauseFamily,
    OnePageExportConfigurationError,
    OnePageExportProfileBundle,
    OnePageExportStage,
)


def _chunking_profile() -> ChunkingProfile:
    return ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=96,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository="https://huggingface.co/BAAI/bge-m3",
        tokenizer_revision="5617a9f61b028005a4858fdac845db406aefb181",
        observed_license="MIT",
        provenance_url=(
            "https://huggingface.co/BAAI/bge-m3/tree/"
            "5617a9f61b028005a4858fdac845db406aefb181"
        ),
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17098108,
                sha256=(
                    "21106b6d7dab2952c1d496fb21d5dc9d"
                    "b75c28ed361a05f5020bbba27810dd08"
                ),
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )


def _jira_profile() -> JiraRelationProfile:
    return JiraRelationProfile(
        schema_version=1,
        extraction_mode=JIRA_EXTRACTION_MODE,
        key_pattern=JIRA_KEY_PATTERN,
        allowed_project_keys=("SVMCSPEN",),
    )


def _bundle(
    *,
    embedding_text: str = "embedding-profile-text",
    jira_text: str = "jira-profile-text",
) -> OnePageExportProfileBundle:
    return OnePageExportProfileBundle(
        chunking_profile=_chunking_profile(),
        jira_relation_profile=_jira_profile(),
        normalized_embedding_profile_text=embedding_text,
        normalized_jira_relation_profile_text=jira_text,
    )


def test_contract_constants_are_exact() -> None:
    assert ONE_PAGE_DATASET_NAME == "spen_knowledge_poc"
    assert ONE_PAGE_SOURCE_ID == "confluence_svmc_spensrv"
    assert ONE_PAGE_EXPORT_MODE == "full_snapshot"
    assert ONE_PAGE_SCHEMAS_VERSION == "1.0"
    assert ONE_PAGE_CONFIG_CONTRACT_VERSION == "one-page-export-v2"
    assert ONE_PAGE_NORMALIZATION_POLICY_ID == "confluence-table-no-loss-v1"
    assert ONE_PAGE_SPACE_KEY == "SVMC"


def test_bundle_computes_deterministic_config_hash() -> None:
    first = _bundle()
    second = _bundle()
    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 64
    assert all(char in "0123456789abcdef" for char in first.config_hash)


def test_bundle_config_hash_changes_with_normalized_text() -> None:
    baseline = _bundle()
    changed = _bundle(embedding_text="different-embedding-profile-text")
    assert baseline.config_hash != changed.config_hash


def test_bundle_config_hash_uses_canonical_json_algorithm() -> None:
    import hashlib
    import json

    bundle = _bundle()
    canonical = {
        "contract_version": ONE_PAGE_CONFIG_CONTRACT_VERSION,
        "dataset_name": ONE_PAGE_DATASET_NAME,
        "normalization_policy_id": ONE_PAGE_NORMALIZATION_POLICY_ID,
        "source_id": ONE_PAGE_SOURCE_ID,
        "embedding_profile_text": "embedding-profile-text",
        "jira_relation_profile_text": "jira-profile-text",
    }
    expected = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert bundle.config_hash == expected


def test_table_policy_identity_invalidates_the_previous_export_hash() -> None:
    import hashlib
    import json

    old_canonical = {
        "contract_version": "one-page-export-v1",
        "dataset_name": ONE_PAGE_DATASET_NAME,
        "source_id": ONE_PAGE_SOURCE_ID,
        "embedding_profile_text": "embedding-profile-text",
        "jira_relation_profile_text": "jira-profile-text",
    }
    old_hash = hashlib.sha256(
        json.dumps(
            old_canonical,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert _bundle().config_hash != old_hash


def test_config_hash_cannot_be_supplied_or_overridden() -> None:
    with pytest.raises(TypeError):
        OnePageExportProfileBundle(
            chunking_profile=_chunking_profile(),
            jira_relation_profile=_jira_profile(),
            normalized_embedding_profile_text="a",
            normalized_jira_relation_profile_text="b",
            config_hash="deadbeef",
        )


@pytest.mark.parametrize(
    "field_name",
    ["normalized_embedding_profile_text", "normalized_jira_relation_profile_text"],
)
def test_non_canonical_normalized_text_is_rejected(field_name: str) -> None:
    kwargs = {
        "chunking_profile": _chunking_profile(),
        "jira_relation_profile": _jira_profile(),
        "normalized_embedding_profile_text": "a",
        "normalized_jira_relation_profile_text": "b",
    }
    kwargs[field_name] = "trailing space \n\n\n"
    with pytest.raises(ValueError):
        OnePageExportProfileBundle(**kwargs)


def test_non_string_normalized_text_is_rejected() -> None:
    with pytest.raises(TypeError):
        _bundle(embedding_text=123)  # type: ignore[arg-type]


def test_wrong_typed_profiles_are_rejected() -> None:
    with pytest.raises(TypeError):
        OnePageExportProfileBundle(
            chunking_profile="not-a-profile",  # type: ignore[arg-type]
            jira_relation_profile=_jira_profile(),
            normalized_embedding_profile_text="a",
            normalized_jira_relation_profile_text="b",
        )
    with pytest.raises(TypeError):
        OnePageExportProfileBundle(
            chunking_profile=_chunking_profile(),
            jira_relation_profile="not-a-profile",  # type: ignore[arg-type]
            normalized_embedding_profile_text="a",
            normalized_jira_relation_profile_text="b",
        )


def test_bundle_retains_no_raw_or_normalized_text() -> None:
    bundle = _bundle()
    assert not hasattr(bundle, "normalized_embedding_profile_text")
    assert not hasattr(bundle, "normalized_jira_relation_profile_text")


def test_bundle_is_frozen_and_repr_hides_contents() -> None:
    bundle = _bundle()
    with pytest.raises(Exception):
        bundle.config_hash = "x"  # type: ignore[misc]
    rendered = repr(bundle)
    assert "embedding-profile-text" not in rendered
    assert "jira-profile-text" not in rendered


def test_export_configuration_error_str_is_stable_category() -> None:
    error = OnePageExportConfigurationError(
        stage=OnePageExportStage.EMBEDDING_PROFILE_READ,
        cause_family=OnePageExportCauseFamily.IO_ERROR,
    )
    assert str(error) == "export_configuration"
    assert "embedding_profile_read" not in repr(error)
    assert "io_error" not in repr(error)


@pytest.mark.parametrize(
    ("stage", "cause_family"),
    [
        ("embedding_profile_read", OnePageExportCauseFamily.IO_ERROR),
        (OnePageExportStage.EMBEDDING_PROFILE_READ, "io_error"),
        (object(), OnePageExportCauseFamily.IO_ERROR),
        (OnePageExportStage.EMBEDDING_PROFILE_READ, object()),
    ],
)
def test_export_configuration_error_requires_typed_closed_values(
    stage: object,
    cause_family: object,
) -> None:
    with pytest.raises(TypeError):
        OnePageExportConfigurationError(  # type: ignore[arg-type]
            stage=stage,
            cause_family=cause_family,
        )
