"""Shared fixture builders for M6G-C quality-report-input/exporter/CLI tests.

Builds a small, internally-consistent one-document/one-chunk/one-relation/
one-ACL-record fixture set: exactly the shape the R9 integrity relations in
``OnePageExportQualityReportInput`` expect (``relations_total == 1``,
``documents_enriched == 1``, ``chunks_enriched == chunks_total == 1``,
``acl_records_total == 1``).
"""

from __future__ import annotations

from knowledgenexus.foundation.application.use_cases.project_one_page_export import (
    OnePageExportProjection,
)
from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    JiraRelationQualityObservation,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
    ONE_PAGE_EXPORT_MODE,
    ONE_PAGE_SCHEMAS_VERSION,
    ONE_PAGE_SOURCE_ID,
)
from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    OnePageExportQualityReportInput,
)
from tests.fixtures.foundation.record_factories import (
    JIRA_KEY,
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)

CHUNKER_VERSION = "1.0.0"
ACTIVE_PROFILE = "medium"
PROFILE_STATUS = "provisional_until_benchmark"
CONFIG_HASH = "b" * 64

EXPECTED_COUNTS: dict[str, int] = {
    "documents": 1,
    "chunks": 1,
    "relations": 1,
    "acl": 1,
    "media_assets": 0,
    "symbols": 0,
    "sync_state": 0,
    "tombstones": 0,
}

FULL_JIRA_METRICS: dict[str, object] = {
    "candidate_occurrences": 1,
    "unique_key_like_count": 1,
    "allowlisted_unique_count": 1,
    "outside_allowlist_unique_count": 0,
    "duplicate_occurrences": 0,
    "relations_total": 1,
    "documents_enriched": 1,
    "chunks_enriched": 1,
}

FULL_ACL_METRICS: dict[str, object] = {
    "acl_records_total": 1,
    "chunks_total": 1,
    "chunks_acl_changed": 0,
    "restriction_observations_total": 1,
    "available_observations": 1,
    "unavailable_observations": 0,
    "restricted_levels": 0,
    "unrestricted_levels": 1,
    "observed_user_envelope_occurrences": 0,
    "observed_group_envelope_occurrences": 0,
    "unique_valid_user_principals": 0,
    "unique_valid_group_principals": 0,
    "non_enforceable_user_occurrences": 0,
    "non_enforceable_group_occurrences": 0,
    "user_principals_dropped_by_intersection": 0,
    "group_principals_dropped_by_intersection": 0,
    "effective_users": 0,
    "effective_groups": 0,
    "default_deny_records": 0,
    "partial_acl_records": 0,
    "unavailable_acl_records": 0,
    "manual_review_records": 0,
}


def build_jira_quality_observation(**overrides: object) -> JiraRelationQualityObservation:
    fields: dict[str, object] = {
        "unique_key_like_candidates": (JIRA_KEY,),
        "allowlisted_keys": (JIRA_KEY,),
        "outside_allowlist_keys": (),
    }
    fields.update(overrides)
    return JiraRelationQualityObservation(**fields)  # type: ignore[arg-type]


def build_acl_quality_observation(**overrides: object) -> AclQualityObservation:
    fields: dict[str, object] = {
        "restriction_observations_total": 1,
        "available_observations": 1,
        "unavailable_observations": 0,
        "restricted_levels": 0,
        "unrestricted_levels": 1,
        "observed_user_envelope_occurrences": 0,
        "observed_group_envelope_occurrences": 0,
        "unique_valid_user_principals": 0,
        "unique_valid_group_principals": 0,
        "non_enforceable_user_occurrences": 0,
        "non_enforceable_group_occurrences": 0,
        "user_principals_dropped_by_intersection": 0,
        "group_principals_dropped_by_intersection": 0,
        "effective_users": 0,
        "effective_groups": 0,
        "default_deny_applied": False,
        "manual_review_required": False,
        "reason_codes": (),
    }
    fields.update(overrides)
    return AclQualityObservation(**fields)  # type: ignore[arg-type]


def build_quality_report_input(**overrides: object) -> OnePageExportQualityReportInput:
    fields: dict[str, object] = {
        "active_profile": ACTIVE_PROFILE,
        "profile_status": PROFILE_STATUS,
        "chunker_version": CHUNKER_VERSION,
        "expected_counts": dict(EXPECTED_COUNTS),
        "jira_quality_observation": build_jira_quality_observation(),
        "jira_metrics": dict(FULL_JIRA_METRICS),
        "acl_quality_observation": build_acl_quality_observation(),
        "acl_metrics": dict(FULL_ACL_METRICS),
    }
    fields.update(overrides)
    return OnePageExportQualityReportInput(**fields)  # type: ignore[arg-type]


def build_one_page_export_projection(**overrides: object) -> OnePageExportProjection:
    document = build_sample_document_record()
    chunk = build_sample_chunk_record()
    relation = build_sample_relation_record()
    acl_record = build_sample_acl_record()

    fields: dict[str, object] = {
        "dataset_name": ONE_PAGE_DATASET_NAME,
        "source_id": ONE_PAGE_SOURCE_ID,
        "export_mode": ONE_PAGE_EXPORT_MODE,
        "schemas_version": ONE_PAGE_SCHEMAS_VERSION,
        "documents": (document,),
        "chunks": (chunk,),
        "relations": (relation,),
        "acl": (acl_record,),
        "media_assets": (),
        "symbols": (),
        "sync_state": (),
        "tombstones": (),
        "source_scopes": {
            "confluence": {
                "source_ids": [ONE_PAGE_SOURCE_ID],
                "space_keys": ["SVMC"],
                "page_ids": ["123"],
            }
        },
        "chunker_version": CHUNKER_VERSION,
        "active_profile": ACTIVE_PROFILE,
        "profile_status": PROFILE_STATUS,
        "config_hash": CONFIG_HASH,
        "jira_quality_observation": build_jira_quality_observation(),
        "jira_metrics": dict(FULL_JIRA_METRICS),
        "acl_quality_observation": build_acl_quality_observation(),
        "acl_metrics": dict(FULL_ACL_METRICS),
    }
    fields.update(overrides)
    return OnePageExportProjection(**fields)  # type: ignore[arg-type]
