from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    ACL_METRICS_KEY_ORDER,
    JIRA_METRICS_KEY_ORDER,
    OnePageExportAcceptanceResult,
    OnePageExportQualityReportInput,
    OnePageExportQualityReportInputError,
    OnePageFullSnapshotExportResult,
)
from tests.fixtures.foundation.one_page_export_snapshot_fixtures import (
    FULL_ACL_METRICS,
    build_acl_quality_observation,
    build_jira_quality_observation,
    build_quality_report_input,
)


def _acceptance(**overrides: object) -> OnePageExportAcceptanceResult:
    fields: dict[str, object] = {
        "final_file_set_valid": True,
        "manifest_schema_valid": True,
        "manifest_version_matches_directory": True,
        "manifest_metadata_matches_projection": True,
        "manifest_counts_match": True,
        "records_match_projection": True,
        "deferred_streams_empty": True,
        "quality_report_unchanged_after_publication": True,
        "latest_pointer_valid": True,
    }
    fields.update(overrides)
    return OnePageExportAcceptanceResult(**fields)  # type: ignore[arg-type]


# --- OnePageExportQualityReportInput: success --------------------------------


def test_success_construction_pins_key_order_and_copies_ownership() -> None:
    expected_counts = {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 0,
    }
    quality_input = build_quality_report_input(expected_counts=expected_counts)

    assert tuple(quality_input.expected_counts) == (
        "documents",
        "chunks",
        "relations",
        "acl",
        "media_assets",
        "symbols",
        "sync_state",
        "tombstones",
    )
    assert tuple(quality_input.jira_metrics) == JIRA_METRICS_KEY_ORDER
    assert tuple(quality_input.acl_metrics) == ACL_METRICS_KEY_ORDER

    expected_counts["documents"] = 999
    assert quality_input.expected_counts["documents"] == 1


# --- expected_counts ----------------------------------------------------------


def test_expected_counts_missing_key_rejected() -> None:
    counts = {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(expected_counts=counts)


def test_expected_counts_extra_key_rejected() -> None:
    counts = {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 0,
        "extra": 0,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(expected_counts=counts)


@pytest.mark.parametrize("bad_value", [-1, True, "1", 1.0])
def test_expected_counts_rejects_non_negative_int_violation(bad_value: object) -> None:
    counts = {
        "documents": bad_value,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 0,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(expected_counts=counts)


# --- jira_metrics / acl_metrics vocabulary -------------------------------------


def test_jira_metrics_missing_key_rejected() -> None:
    metrics = {
        "candidate_occurrences": 1,
        "unique_key_like_count": 1,
        "allowlisted_unique_count": 1,
        "outside_allowlist_unique_count": 0,
        "duplicate_occurrences": 0,
        "relations_total": 1,
        "documents_enriched": 1,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=metrics)


def test_jira_metrics_unrecognized_key_rejected() -> None:
    metrics = {
        "candidate_occurrences": 1,
        "unique_key_like_count": 1,
        "allowlisted_unique_count": 1,
        "outside_allowlist_unique_count": 0,
        "duplicate_occurrences": 0,
        "relations_total": 1,
        "documents_enriched": 1,
        "chunks_enriched": 1,
        "unexpected_metric": 0,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=metrics)


def test_acl_metrics_missing_key_rejected() -> None:
    metrics = {key: 0 for key in ACL_METRICS_KEY_ORDER[:-1]}
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=metrics)


def test_acl_metrics_unrecognized_key_rejected() -> None:
    metrics = {key: 0 for key in ACL_METRICS_KEY_ORDER}
    metrics["acl_records_total"] = 1
    metrics["chunks_total"] = 1
    metrics["unexpected_metric"] = 0
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=metrics)


def test_jira_quality_observation_wrong_type_rejected() -> None:
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_quality_observation=object())


def test_acl_quality_observation_wrong_type_rejected() -> None:
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_quality_observation=object())


# --- R9 re-derivable integrity relations ---------------------------------------


def test_allowlisted_unique_count_inconsistent_with_observation_rejected() -> None:
    jira_metrics = {
        "candidate_occurrences": 2,
        "unique_key_like_count": 2,
        "allowlisted_unique_count": 2,
        "outside_allowlist_unique_count": 0,
        "duplicate_occurrences": 0,
        "relations_total": 1,
        "documents_enriched": 1,
        "chunks_enriched": 1,
    }
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(
            jira_metrics=jira_metrics,
            jira_quality_observation=build_jira_quality_observation(
                allowlisted_keys=("ONLY-ONE",)
            ),
        )


def test_unique_key_like_count_inconsistent_with_candidates_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=999,
        unique_key_like_count=999,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=998,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_outside_allowlist_unique_count_inconsistent_with_keys_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=1,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=5,
        duplicate_occurrences=0,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_candidate_occurrences_below_unique_key_like_count_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=0,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_duplicate_occurrences_inconsistent_with_candidate_algebra_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=3,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_acl_metrics_direct_mirror_field_inconsistent_with_observation_rejected() -> None:
    acl_metrics = dict(FULL_ACL_METRICS)
    acl_metrics["restriction_observations_total"] = 999
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=acl_metrics)


def test_reviewer_reproduction_both_wrong_999_values_rejected() -> None:
    # Reproduces the accepted review finding: unique_key_like_count=999 and
    # acl_metrics.restriction_observations_total=999 must each independently
    # fail construction rather than both being silently accepted.
    jira_metrics = dict(
        candidate_occurrences=999,
        unique_key_like_count=999,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=998,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)

    acl_metrics = dict(FULL_ACL_METRICS)
    acl_metrics["restriction_observations_total"] = 999
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=acl_metrics)


def test_relations_total_inconsistent_with_expected_counts_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=1,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=2,
        documents_enriched=1,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_documents_enriched_out_of_range_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=1,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=1,
        documents_enriched=2,
        chunks_enriched=1,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_documents_enriched_inconsistent_with_relations_total_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=1,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=0,
        documents_enriched=1,
        chunks_enriched=0,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_chunks_enriched_inconsistent_with_expected_counts_rejected() -> None:
    jira_metrics = dict(
        candidate_occurrences=1,
        unique_key_like_count=1,
        allowlisted_unique_count=1,
        outside_allowlist_unique_count=0,
        duplicate_occurrences=0,
        relations_total=1,
        documents_enriched=1,
        chunks_enriched=0,
    )
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(jira_metrics=jira_metrics)


def test_acl_records_total_must_be_exactly_one() -> None:
    acl_metrics = {key: 0 for key in ACL_METRICS_KEY_ORDER}
    acl_metrics["acl_records_total"] = 2
    acl_metrics["chunks_total"] = 1
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=acl_metrics)


def test_acl_chunks_total_inconsistent_with_expected_counts_rejected() -> None:
    acl_metrics = {key: 0 for key in ACL_METRICS_KEY_ORDER}
    acl_metrics["acl_records_total"] = 1
    acl_metrics["chunks_total"] = 5
    with pytest.raises(OnePageExportQualityReportInputError):
        build_quality_report_input(acl_metrics=acl_metrics)


def test_acl_quality_observation_field_order_matches_dataclass_declaration() -> None:
    quality = build_acl_quality_observation()
    field_names = tuple(quality.__dataclass_fields__)
    assert field_names == (
        "restriction_observations_total",
        "available_observations",
        "unavailable_observations",
        "restricted_levels",
        "unrestricted_levels",
        "observed_user_envelope_occurrences",
        "observed_group_envelope_occurrences",
        "unique_valid_user_principals",
        "unique_valid_group_principals",
        "non_enforceable_user_occurrences",
        "non_enforceable_group_occurrences",
        "user_principals_dropped_by_intersection",
        "group_principals_dropped_by_intersection",
        "effective_users",
        "effective_groups",
        "default_deny_applied",
        "manual_review_required",
        "reason_codes",
    )


# --- OnePageExportAcceptanceResult ---------------------------------------------


def test_acceptance_result_requires_bool_fields() -> None:
    with pytest.raises(TypeError):
        _acceptance(final_file_set_valid=1)


def test_acceptance_result_success() -> None:
    result = _acceptance()
    assert result.latest_pointer_valid is True


# --- OnePageFullSnapshotExportResult --------------------------------------------


def test_export_result_copies_manifest_ownership(tmp_path: Path) -> None:
    manifest = {"dataset_version": "v1"}
    result = OnePageFullSnapshotExportResult(
        dataset_version="v1",
        final_path=tmp_path / "v1",
        manifest=manifest,
        acceptance=_acceptance(),
    )
    manifest["dataset_version"] = "tampered"
    assert result.manifest == {"dataset_version": "v1"}


def test_export_result_rejects_wrong_types(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        OnePageFullSnapshotExportResult(
            dataset_version="v1",
            final_path=str(tmp_path / "v1"),
            manifest={},
            acceptance=_acceptance(),
        )
