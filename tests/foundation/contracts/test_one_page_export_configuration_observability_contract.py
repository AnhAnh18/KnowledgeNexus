from __future__ import annotations

from pathlib import Path

from knowledgenexus.foundation.domain.models.one_page_export import (
    OnePageExportCauseFamily,
    OnePageExportStage,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "ONE_PAGE_EXPORT_SPEC.md"

EXPECTED_STAGES = {
    "embedding_profile_read",
    "embedding_profile_decode",
    "embedding_profile_parse",
    "jira_profile_read",
    "jira_profile_decode",
    "jira_profile_parse",
    "profile_bundle_construction",
    "export_input_validation",
    "generated_at_validation",
    "dataset_root_validation",
    "dataset_version_generation",
}
EXPECTED_CAUSES = {
    "io_error",
    "text_decode_error",
    "profile_validation_error",
    "type_error",
    "value_error",
    "unexpected_error",
}


def test_runtime_vocabulary_matches_the_focused_contract() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert {stage.value for stage in OnePageExportStage} == EXPECTED_STAGES
    assert {
        cause.value for cause in OnePageExportCauseFamily
    } == EXPECTED_CAUSES
    for value in EXPECTED_STAGES | EXPECTED_CAUSES:
        assert spec.count(value) >= 1


def test_contract_locks_additive_exit_14_compatibility_and_schema_boundary() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert "Exit code 14 (`export_configuration`)" in spec
    assert '"status": "failed"' in spec
    assert '"category": "export_configuration"' in spec
    assert '"stage": "<one of 11 stage values>"' in spec
    assert '"cause_family": "<one of 6 cause_family values>"' in spec
    assert "Successful CLI" in spec
    assert "Foundation JSON Schema" in spec
