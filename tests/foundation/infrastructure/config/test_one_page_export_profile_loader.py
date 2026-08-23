from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportCauseFamily,
    OnePageExportStage,
)
from knowledgenexus.foundation.infrastructure.config import (
    one_page_export_profile_loader as loader_module,
)
from knowledgenexus.foundation.infrastructure.config import (
    OnePageExportConfigurationError,
    load_one_page_export_profile_bundle,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    ChunkingProfileLoadError,
)
from knowledgenexus.foundation.infrastructure.config.jira_relation_profile_loader import (
    JiraRelationProfileLoadError,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
EMBEDDING_PROFILE_PATH = (
    REPOSITORY_ROOT / "config" / "foundation" / "embedding_profile.yaml"
)
JIRA_PROFILE_PATH = (
    REPOSITORY_ROOT / "contracts" / "foundation" / "jira_relation_profile.yaml"
)

_JIRA_YAML = (
    "schema_version: 1\n"
    "extraction_mode: regex_only\n"
    "key_pattern: '(?<![A-Za-z0-9_])(?P<key>[A-Z][A-Z0-9_]+-[0-9]+)(?![A-Za-z0-9_])'\n"
    "allowed_project_keys:\n"
    "  - SVMCSPEN\n"
)


def test_loads_the_real_active_contract_profiles() -> None:
    bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=JIRA_PROFILE_PATH,
    )
    assert bundle.chunking_profile.chunker_version == "1.3.0"
    assert bundle.jira_relation_profile.allowed_project_keys == ("SVMCSPEN",)
    assert len(bundle.config_hash) == 64


def test_config_hash_is_deterministic_across_two_loads() -> None:
    first = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=JIRA_PROFILE_PATH,
    )
    second = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=JIRA_PROFILE_PATH,
    )
    assert first.config_hash == second.config_hash


def test_crlf_and_lf_profile_bytes_parse_and_hash_identically(
    tmp_path: Path,
) -> None:
    # R6: the bundle loader decodes exact bytes with no newline translation,
    # so a CRLF file reaches parse_jira_relation_profile_text() unnormalized.
    # YAML parses CRLF/LF identically, and TextNormalizationRules collapses
    # CRLF before hashing, so the resulting config_hash is the same either way.
    lf_path = tmp_path / "jira-lf.yaml"
    lf_path.write_bytes(_JIRA_YAML.encode("utf-8"))
    crlf_path = tmp_path / "jira-crlf.yaml"
    crlf_path.write_bytes(_JIRA_YAML.replace("\n", "\r\n").encode("utf-8"))

    lf_bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=lf_path,
    )
    crlf_bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=crlf_path,
    )
    assert lf_bundle.config_hash == crlf_bundle.config_hash


def test_trailing_whitespace_does_not_change_the_hash(tmp_path: Path) -> None:
    padded_path = tmp_path / "jira-padded.yaml"
    padded_path.write_bytes(
        (_JIRA_YAML.rstrip("\n") + "   \n\n\n").encode("utf-8")
    )
    baseline_path = tmp_path / "jira-baseline.yaml"
    baseline_path.write_bytes(_JIRA_YAML.encode("utf-8"))

    padded_bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=padded_path,
    )
    baseline_bundle = load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=baseline_path,
    )
    assert padded_bundle.config_hash == baseline_bundle.config_hash


def test_invalid_utf8_bundle_input_yields_export_configuration(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid-utf8.yaml"
    invalid_path.write_bytes(b"\xff\xfe\x00schema_version: 1")

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=EMBEDDING_PROFILE_PATH,
            jira_relation_profile_path=invalid_path,
        )
    assert str(exc_info.value) == "export_configuration"
    assert exc_info.value.stage == OnePageExportStage.JIRA_PROFILE_DECODE
    assert (
        exc_info.value.cause_family
        == OnePageExportCauseFamily.TEXT_DECODE_ERROR
    )
    assert str(invalid_path) not in str(exc_info.value)


def test_invalid_utf8_embedding_profile_has_decode_stage(tmp_path: Path) -> None:
    invalid_path = tmp_path / "SENSITIVE-embedding.yaml"
    invalid_path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=invalid_path,
            jira_relation_profile_path=JIRA_PROFILE_PATH,
        )

    assert exc_info.value.stage == OnePageExportStage.EMBEDDING_PROFILE_DECODE
    assert (
        exc_info.value.cause_family
        == OnePageExportCauseFamily.TEXT_DECODE_ERROR
    )
    assert "SENSITIVE" not in str(exc_info.value)


def test_missing_profile_yields_export_configuration(tmp_path: Path) -> None:
    missing = tmp_path / "SENSITIVE-missing.yaml"

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=missing,
            jira_relation_profile_path=JIRA_PROFILE_PATH,
        )
    assert exc_info.value.stage == OnePageExportStage.EMBEDDING_PROFILE_READ
    assert exc_info.value.cause_family == OnePageExportCauseFamily.IO_ERROR
    assert "SENSITIVE" not in str(exc_info.value)


def test_malformed_profile_yields_export_configuration(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.yaml"
    malformed_path.write_text("not: a, valid: [profile", encoding="utf-8")

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=EMBEDDING_PROFILE_PATH,
            jira_relation_profile_path=malformed_path,
        )
    assert exc_info.value.stage == OnePageExportStage.JIRA_PROFILE_PARSE
    assert (
        exc_info.value.cause_family
        == OnePageExportCauseFamily.PROFILE_VALIDATION_ERROR
    )


def test_wrong_typed_paths_raise_typeerror() -> None:
    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path="not-a-path",  # type: ignore[arg-type]
            jira_relation_profile_path=JIRA_PROFILE_PATH,
        )
    assert exc_info.value.stage == OnePageExportStage.EXPORT_INPUT_VALIDATION
    assert exc_info.value.cause_family == OnePageExportCauseFamily.TYPE_ERROR
    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=EMBEDDING_PROFILE_PATH,
            jira_relation_profile_path="not-a-path",  # type: ignore[arg-type]
        )
    assert exc_info.value.stage == OnePageExportStage.EXPORT_INPUT_VALIDATION
    assert exc_info.value.cause_family == OnePageExportCauseFamily.TYPE_ERROR


def _raise(error: Exception) -> None:
    raise error


@pytest.mark.parametrize(
    ("parser_name", "failure", "expected_stage", "expected_cause"),
    [
        (
            "parse_chunking_profile_text",
            ChunkingProfileLoadError("SENSITIVE profile fragment"),
            OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            OnePageExportCauseFamily.PROFILE_VALIDATION_ERROR,
        ),
        (
            "parse_chunking_profile_text",
            TypeError("SENSITIVE type"),
            OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            OnePageExportCauseFamily.TYPE_ERROR,
        ),
        (
            "parse_chunking_profile_text",
            ValueError("SENSITIVE value"),
            OnePageExportStage.EMBEDDING_PROFILE_PARSE,
            OnePageExportCauseFamily.VALUE_ERROR,
        ),
        (
            "parse_jira_relation_profile_text",
            JiraRelationProfileLoadError("SENSITIVE profile fragment"),
            OnePageExportStage.JIRA_PROFILE_PARSE,
            OnePageExportCauseFamily.PROFILE_VALIDATION_ERROR,
        ),
        (
            "parse_jira_relation_profile_text",
            TypeError("SENSITIVE type"),
            OnePageExportStage.JIRA_PROFILE_PARSE,
            OnePageExportCauseFamily.TYPE_ERROR,
        ),
        (
            "parse_jira_relation_profile_text",
            ValueError("SENSITIVE value"),
            OnePageExportStage.JIRA_PROFILE_PARSE,
            OnePageExportCauseFamily.VALUE_ERROR,
        ),
    ],
)
def test_parser_failures_map_to_exact_sanitized_metadata(
    parser_name: str,
    failure: Exception,
    expected_stage: OnePageExportStage,
    expected_cause: OnePageExportCauseFamily,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        loader_module,
        parser_name,
        lambda raw_text: _raise(failure),
    )

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=EMBEDDING_PROFILE_PATH,
            jira_relation_profile_path=JIRA_PROFILE_PATH,
        )

    assert exc_info.value.stage == expected_stage
    assert exc_info.value.cause_family == expected_cause
    assert "SENSITIVE" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("failure", "expected_cause"),
    [
        (TypeError("SENSITIVE type"), OnePageExportCauseFamily.TYPE_ERROR),
        (ValueError("SENSITIVE value"), OnePageExportCauseFamily.VALUE_ERROR),
    ],
)
def test_bundle_construction_failures_are_sanitized(
    failure: Exception,
    expected_cause: OnePageExportCauseFamily,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        loader_module,
        "OnePageExportProfileBundle",
        lambda **kwargs: _raise(failure),
    )

    with pytest.raises(OnePageExportConfigurationError) as exc_info:
        load_one_page_export_profile_bundle(
            embedding_profile_path=EMBEDDING_PROFILE_PATH,
            jira_relation_profile_path=JIRA_PROFILE_PATH,
        )

    assert exc_info.value.stage == OnePageExportStage.PROFILE_BUNDLE_CONSTRUCTION
    assert exc_info.value.cause_family == expected_cause
    assert "SENSITIVE" not in str(exc_info.value)


def test_each_profile_is_read_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_bytes = Path.read_bytes
    calls: dict[Path, int] = {}

    def count_read(path: Path) -> bytes:
        calls[path] = calls.get(path, 0) + 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_read)

    load_one_page_export_profile_bundle(
        embedding_profile_path=EMBEDDING_PROFILE_PATH,
        jira_relation_profile_path=JIRA_PROFILE_PATH,
    )

    assert calls == {EMBEDDING_PROFILE_PATH: 1, JIRA_PROFILE_PATH: 1}
