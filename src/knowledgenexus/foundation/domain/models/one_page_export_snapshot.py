"""Bounded quality-report input and export result models (M6G-C, spec §9).

``OnePageExportQualityReportInput`` exists so the extended
``FullSnapshotStagingCompleter`` path never receives the full
``OnePageExportProjection`` (which carries document/chunk/ACL record contents
the report does not need). ``__post_init__`` re-checks the re-derivable
algebraic relations already locked by ``ACL_MATERIALIZATION_SPEC.md`` §2.5 and
§8-9 -- this is integrity checking of already-trusted M6E/M6F values, never a
recomputation of Jira/ACL policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledgenexus.foundation.domain.models.acl_materialization_result import (
    AclQualityObservation,
)
from knowledgenexus.foundation.domain.models.confluence_jira_relations import (
    JiraRelationQualityObservation,
    copy_json_object,
)

COUNT_KEYS: tuple[str, ...] = (
    "documents",
    "chunks",
    "relations",
    "acl",
    "media_assets",
    "symbols",
    "sync_state",
    "tombstones",
)

# The known M6E Jira metrics vocabulary (ACL_MATERIALIZATION_SPEC.md §2.5),
# carried forward unchanged by ConfluenceAclMaterializationResult.jira_metrics.
JIRA_METRICS_KEY_ORDER: tuple[str, ...] = (
    "candidate_occurrences",
    "unique_key_like_count",
    "allowlisted_unique_count",
    "outside_allowlist_unique_count",
    "duplicate_occurrences",
    "relations_total",
    "documents_enriched",
    "chunks_enriched",
)

# The known M6F ACL metrics vocabulary (ACL_MATERIALIZATION_SPEC.md §9).
ACL_METRICS_KEY_ORDER: tuple[str, ...] = (
    "acl_records_total",
    "chunks_total",
    "chunks_acl_changed",
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
    "default_deny_records",
    "partial_acl_records",
    "unavailable_acl_records",
    "manual_review_records",
)

# acl_metrics keys that are direct mirrors of an AclQualityObservation count
# field of the exact same name (ACL_MATERIALIZATION_SPEC.md §8-9) -- these
# must be re-checked for equality, not just type/vocabulary.
_ACL_METRICS_DIRECT_MIRROR_FIELDS: tuple[str, ...] = (
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
)


class OnePageExportQualityReportInputError(ValueError):
    """A bounded quality-report input construction/integrity failure."""


def _require_non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OnePageExportQualityReportInputError(
            f"{name} expects a non-negative int"
        )


@dataclass(frozen=True, repr=False)
class OnePageExportQualityReportInput:
    """Bounded, ownership-isolated input for the extended quality report.

    Carries only what the extended quality report renders, never the full
    ``OnePageExportProjection``'s document/chunk/ACL record contents.
    """

    active_profile: str
    profile_status: str
    chunker_version: str
    expected_counts: dict[str, int]
    jira_quality_observation: JiraRelationQualityObservation
    jira_metrics: dict[str, object]
    acl_quality_observation: AclQualityObservation
    acl_metrics: dict[str, object]

    def __post_init__(self) -> None:
        for name in ("active_profile", "profile_status", "chunker_version"):
            if not isinstance(getattr(self, name), str):
                raise OnePageExportQualityReportInputError(f"{name} expects str")

        if not isinstance(self.expected_counts, dict):
            raise OnePageExportQualityReportInputError(
                "expected_counts expects dict"
            )
        if set(self.expected_counts) != set(COUNT_KEYS):
            raise OnePageExportQualityReportInputError(
                "expected_counts must contain exactly the eight count keys"
            )
        for key in COUNT_KEYS:
            _require_non_negative_int(
                self.expected_counts[key], f"expected_counts[{key}]"
            )
        object.__setattr__(
            self,
            "expected_counts",
            {key: self.expected_counts[key] for key in COUNT_KEYS},
        )

        if not isinstance(
            self.jira_quality_observation, JiraRelationQualityObservation
        ):
            raise OnePageExportQualityReportInputError(
                "jira_quality_observation expects JiraRelationQualityObservation"
            )
        if not isinstance(self.jira_metrics, dict):
            raise OnePageExportQualityReportInputError("jira_metrics expects dict")
        if set(self.jira_metrics) != set(JIRA_METRICS_KEY_ORDER):
            raise OnePageExportQualityReportInputError(
                "jira_metrics must contain exactly the known M6E metric vocabulary"
            )
        for key in JIRA_METRICS_KEY_ORDER:
            _require_non_negative_int(self.jira_metrics[key], f"jira_metrics[{key}]")

        if not isinstance(self.acl_quality_observation, AclQualityObservation):
            raise OnePageExportQualityReportInputError(
                "acl_quality_observation expects AclQualityObservation"
            )
        if not isinstance(self.acl_metrics, dict):
            raise OnePageExportQualityReportInputError("acl_metrics expects dict")
        if set(self.acl_metrics) != set(ACL_METRICS_KEY_ORDER):
            raise OnePageExportQualityReportInputError(
                "acl_metrics must contain exactly the known M6F metric vocabulary"
            )
        for key in ACL_METRICS_KEY_ORDER:
            _require_non_negative_int(self.acl_metrics[key], f"acl_metrics[{key}]")

        # Ownership-isolate and pin key order so rendering never needs to sort.
        object.__setattr__(
            self,
            "jira_metrics",
            {key: self.jira_metrics[key] for key in JIRA_METRICS_KEY_ORDER},
        )
        object.__setattr__(
            self,
            "acl_metrics",
            {key: self.acl_metrics[key] for key in ACL_METRICS_KEY_ORDER},
        )
        jira_quality = self.jira_quality_observation
        object.__setattr__(
            self,
            "jira_quality_observation",
            JiraRelationQualityObservation(
                unique_key_like_candidates=jira_quality.unique_key_like_candidates,
                allowlisted_keys=jira_quality.allowlisted_keys,
                outside_allowlist_keys=jira_quality.outside_allowlist_keys,
            ),
        )

        self._verify_integrity_relations()

    def _verify_integrity_relations(self) -> None:
        # Re-derivable algebraic relations already locked by
        # ACL_MATERIALIZATION_SPEC.md §2.5 / §8-9 -- integrity re-checks of
        # already-trusted M6E/M6F values, never a recomputation of policy.
        jira_metrics = self.jira_metrics
        jira_quality = self.jira_quality_observation
        if len(jira_quality.unique_key_like_candidates) != jira_metrics["unique_key_like_count"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.unique_key_like_count is inconsistent with "
                "jira_quality_observation.unique_key_like_candidates"
            )
        if len(jira_quality.allowlisted_keys) != jira_metrics["allowlisted_unique_count"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.allowlisted_unique_count is inconsistent with "
                "jira_quality_observation.allowlisted_keys"
            )
        if len(jira_quality.outside_allowlist_keys) != jira_metrics["outside_allowlist_unique_count"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.outside_allowlist_unique_count is inconsistent with "
                "jira_quality_observation.outside_allowlist_keys"
            )
        if jira_metrics["candidate_occurrences"] < jira_metrics["unique_key_like_count"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.candidate_occurrences must be >= unique_key_like_count"
            )
        if jira_metrics["duplicate_occurrences"] != (
            jira_metrics["candidate_occurrences"] - jira_metrics["unique_key_like_count"]
        ):
            raise OnePageExportQualityReportInputError(
                "jira_metrics.duplicate_occurrences is inconsistent with "
                "candidate_occurrences - unique_key_like_count"
            )
        if jira_metrics["relations_total"] != self.expected_counts["relations"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.relations_total is inconsistent with "
                "expected_counts.relations"
            )
        if jira_metrics["documents_enriched"] not in (0, 1):
            raise OnePageExportQualityReportInputError(
                "jira_metrics.documents_enriched must be 0 or 1"
            )
        expected_documents_enriched = 1 if jira_metrics["relations_total"] else 0
        if jira_metrics["documents_enriched"] != expected_documents_enriched:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.documents_enriched is inconsistent with "
                "jira_metrics.relations_total"
            )
        if jira_metrics["documents_enriched"] > self.expected_counts["documents"]:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.documents_enriched is inconsistent with "
                "expected_counts.documents"
            )
        expected_chunks_enriched = (
            self.expected_counts["chunks"] if jira_metrics["relations_total"] else 0
        )
        if jira_metrics["chunks_enriched"] != expected_chunks_enriched:
            raise OnePageExportQualityReportInputError(
                "jira_metrics.chunks_enriched is inconsistent with "
                "expected_counts.chunks"
            )

        acl_metrics = self.acl_metrics
        acl_quality = self.acl_quality_observation
        if acl_metrics["acl_records_total"] != 1:
            raise OnePageExportQualityReportInputError(
                "acl_metrics.acl_records_total must be exactly 1"
            )
        if acl_metrics["chunks_total"] != self.expected_counts["chunks"]:
            raise OnePageExportQualityReportInputError(
                "acl_metrics.chunks_total is inconsistent with expected_counts.chunks"
            )
        for field_name in _ACL_METRICS_DIRECT_MIRROR_FIELDS:
            if acl_metrics[field_name] != getattr(acl_quality, field_name):
                raise OnePageExportQualityReportInputError(
                    f"acl_metrics.{field_name} is inconsistent with "
                    f"acl_quality_observation.{field_name}"
                )


@dataclass(frozen=True, repr=False)
class OnePageExportAcceptanceResult:
    """Every explicit acceptance check performed by ``OnePageFullSnapshotExporter``."""

    final_file_set_valid: bool
    manifest_schema_valid: bool
    manifest_version_matches_directory: bool
    manifest_metadata_matches_projection: bool
    manifest_counts_match: bool
    records_match_projection: bool
    deferred_streams_empty: bool
    quality_report_unchanged_after_publication: bool
    latest_pointer_valid: bool

    def __post_init__(self) -> None:
        for name in (
            "final_file_set_valid",
            "manifest_schema_valid",
            "manifest_version_matches_directory",
            "manifest_metadata_matches_projection",
            "manifest_counts_match",
            "records_match_projection",
            "deferred_streams_empty",
            "quality_report_unchanged_after_publication",
            "latest_pointer_valid",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} expects bool")


@dataclass(frozen=True, repr=False)
class OnePageFullSnapshotExportResult:
    """The sanitized internal result of one full-snapshot export.

    Consumed internally by the CLI to build its sanitized summary; the CLI
    itself must never print ``final_path``, ``manifest`` contents, or
    ``dataset_version``.
    """

    dataset_version: str
    final_path: Path
    manifest: dict[str, object]
    acceptance: OnePageExportAcceptanceResult

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_version, str):
            raise TypeError("dataset_version expects str")
        if not isinstance(self.final_path, Path):
            raise TypeError("final_path expects Path")
        if not isinstance(self.manifest, dict):
            raise TypeError("manifest expects dict")
        if not isinstance(self.acceptance, OnePageExportAcceptanceResult):
            raise TypeError("acceptance expects OnePageExportAcceptanceResult")
        object.__setattr__(self, "manifest", copy_json_object(self.manifest))
