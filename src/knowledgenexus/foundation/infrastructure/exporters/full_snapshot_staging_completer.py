"""Complete Foundation full-snapshot staging with a quality report."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import re

from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    ACL_METRICS_KEY_ORDER,
    JIRA_METRICS_KEY_ORDER,
    OnePageExportQualityReportInput,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10QualityReportInput
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import (
    EXPECTED_MACHINE_FILES,
    JSONL_FILE_SCHEMA_PAIRS,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


logger = logging.getLogger(__name__)

QUALITY_REPORT_FILE_NAME = "quality_report.md"
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
EXPECTED_COMPLETE_FILES = EXPECTED_MACHINE_FILES | {QUALITY_REPORT_FILE_NAME}
_M10_METRIC_KEYS: dict[str, tuple[str, ...]] = {
    "jira_metrics": ("relations_total", "resolved", "unresolved", "unresolved_without_jira_api", "deferred_mvp", "unresolved_target"),
    "acl_metrics": ("documents_total", "documents_with_acl", "restricted_documents", "default_deny_chunks"),
    "media_metrics": ("assets_total", "processed", "failed", "not_processed"),
    "symbol_metrics": ("symbols_total", "resolved"),
    "sync_metrics": ("rows_total", "active", "pages", "attachments", "files", "repos"),
    "tombstone_metrics": ("rows_total", "initial_empty"),
    "completion_checks": ("schema_validation", "counts_match", "tombstones_empty", "projection_consistency"),
}
_SAFE_IDENTIFIER = re.compile(r"^[^\s\r\n]{1,256}$")
_SAFE_PROFILE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_CONCRETE_PATH_TYPE = type(Path())

_DEFERRED_STREAM_FILE_NAMES: tuple[str, ...] = (
    "media_assets.jsonl",
    "symbols.jsonl",
    "sync_state.jsonl",
    "tombstones.jsonl",
)


class M10QualityCompletionError(ValueError):
    """Sanitized failure for the additive generic M10 report boundary."""


def _validate_m10_quality_input(quality: object) -> None:
    if type(quality) is not M10QualityReportInput or set(vars(quality)) != set(M10QualityReportInput.__dataclass_fields__):
        raise TypeError("m10_quality has invalid fields")
    for name in ("active_profile", "profile_status", "chunker_version"):
        value = getattr(quality, name)
        if type(value) is not str or _SAFE_PROFILE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("m10_quality profile value is invalid")
    counts = quality.expected_counts
    if type(counts) is not dict or set(counts) != set(COUNT_KEYS):
        raise ValueError("m10_quality expected counts are invalid")
    for value in counts.values():
        if type(value) is not int or value < 0:
            raise ValueError("m10_quality expected counts are invalid")
    for name, keys in _M10_METRIC_KEYS.items():
        value = getattr(quality, name)
        if type(value) is not dict or set(value) != set(keys):
            raise ValueError("m10_quality metric keys are invalid")
        for metric in keys:
            item = value[metric]
            if name == "completion_checks":
                if type(item) is not bool or not item:
                    raise ValueError("m10_quality completion checks are invalid")
            elif type(item) is not int or item < 0:
                raise ValueError("m10_quality metric values are invalid")
    j = quality.jira_metrics
    if j["resolved"] + j["unresolved"] != j["relations_total"] or j["unresolved"] != j["unresolved_without_jira_api"] + j["deferred_mvp"] + j["unresolved_target"]:
        raise ValueError("m10_quality Jira metrics are inconsistent")
    a = quality.acl_metrics
    if a["documents_with_acl"] > a["documents_total"] or a["restricted_documents"] > a["documents_total"] or a["default_deny_chunks"] > quality.expected_counts["chunks"]:
        raise ValueError("m10_quality ACL metrics are inconsistent")
    m = quality.media_metrics
    if m["processed"] + m["failed"] + m["not_processed"] != m["assets_total"]:
        raise ValueError("m10_quality media metrics are inconsistent")
    s = quality.symbol_metrics
    if s["resolved"] > s["symbols_total"] or s["symbols_total"] != quality.expected_counts["symbols"]:
        raise ValueError("m10_quality symbol metrics are inconsistent")
    sy = quality.sync_metrics
    if sy["active"] != sy["rows_total"] or sy["pages"] + sy["attachments"] + sy["files"] + sy["repos"] != sy["rows_total"]:
        raise ValueError("m10_quality sync metrics are inconsistent")
    t = quality.tombstone_metrics
    if t["rows_total"] != quality.expected_counts["tombstones"] or t["initial_empty"] != 1 or t["rows_total"] != 0:
        raise ValueError("m10_quality tombstone metrics are inconsistent")
    scopes = quality.source_scopes
    if type(scopes) is not dict or tuple(scopes) != tuple(sorted(scopes)) or set(scopes) not in ({"confluence"}, {"confluence", "git"}):
        raise ValueError("m10_quality source scopes are invalid")
    _validate_m10_scope(scopes)


def _validate_m10_scope(scopes: dict[str, object]) -> None:
    confluence = scopes["confluence"]
    if type(confluence) is not dict or set(confluence) != {"source_id", "space_keys", "root_page_ids", "page_ids"}:
        raise ValueError("m10_quality Confluence scope is invalid")
    for name in ("space_keys", "root_page_ids", "page_ids"):
        values = confluence[name]
        if type(values) not in (tuple, list) or not values or tuple(sorted(values)) != tuple(values) or len(set(values)) != len(values) or any(type(x) is not str or _SAFE_IDENTIFIER.fullmatch(x) is None for x in values):
            raise ValueError("m10_quality scope arrays are invalid")
    if type(confluence["source_id"]) is not str or _SAFE_IDENTIFIER.fullmatch(confluence["source_id"]) is None:
        raise ValueError("m10_quality source ID is invalid")
    if not set(confluence["root_page_ids"]).issubset(confluence["page_ids"]):
        raise ValueError("m10_quality roots are outside page scope")
    if "git" in scopes:
        git = scopes["git"]
        if type(git) is not dict or set(git) != {"repository", "branch", "commit"} or any(type(git[x]) is not str or _SAFE_IDENTIFIER.fullmatch(git[x]) is None for x in ("repository", "branch")) or _HEX40.fullmatch(git["commit"]) is None:
            raise ValueError("m10_quality Git scope is invalid")


def _strict_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_object_keys, parse_constant=_reject_non_finite_constant)
    if type(value) is not dict:
        raise TypeError("manifest must be an object")
    return value


def _validate_m10_streams(*, staging_path: Path, manifest: dict[str, object], validator: FoundationSchemaValidator) -> dict[str, list[dict[str, object]]]:
    streams: dict[str, list[dict[str, object]]] = {}
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        records = _read_strict_jsonl_records(staging_path / file_name)
        if count_key == "tombstones":
            if manifest.get("export_mode") == "full_snapshot" and records:
                raise ValueError("full snapshots must not contain tombstones")
            if manifest.get("export_mode") == "delta":
                for record in records:
                    before = deepcopy(record)
                    isolated = deepcopy(record)
                    validator.validate_record("TombstoneRecord", isolated)
                    if isolated != before:
                        raise ValueError("canonical validator mutated a tombstone")
            streams[count_key] = records
            continue
        if len(records) != manifest["counts"][count_key]:
            raise ValueError("stream count does not match manifest")
        checked: list[dict[str, object]] = []
        for record in records:
            before = deepcopy(record)
            isolated = deepcopy(record)
            validator.validate_record(schema_name, isolated)
            if isolated != before:
                raise ValueError("canonical validator mutated a record")
            checked.append(deepcopy(record))
        streams[count_key] = checked
    return streams


def _complete_m10_quality(*, staging_path: Path, validator: FoundationSchemaValidator, quality: M10QualityReportInput) -> dict[str, object]:
    quality_before = deepcopy(quality)
    if not staging_path.exists() or not staging_path.is_dir():
        raise FileNotFoundError("staging path is unavailable")
    report_path = staging_path / QUALITY_REPORT_FILE_NAME
    if report_path.exists() or report_path.is_symlink():
        raise FileExistsError("quality report already exists")
    _verify_file_set(staging_path, EXPECTED_MACHINE_FILES)
    manifest = _strict_json_object(staging_path / "manifest.json")
    manifest_before = deepcopy(manifest)
    validator.validate_record("Manifest", manifest_before)
    if manifest_before != manifest:
        raise ValueError("canonical validator mutated manifest")
    _verify_full_snapshot_invariants(manifest)
    _validate_m10_scope(manifest.get("source_scopes"))
    if _canonical_json(manifest["source_scopes"]) != _canonical_json(quality.source_scopes):
        raise ValueError("source scope mismatch")
    streams = _validate_m10_streams(staging_path=staging_path, manifest=manifest, validator=validator)
    if _canonical_json(manifest["counts"]) != _canonical_json(quality.expected_counts):
        raise ValueError("quality expected counts mismatch")
    _verify_m10_metric_counts(quality, streams)
    report = _render_m10_quality_report(manifest, quality)
    if quality != quality_before:
        raise ValueError("m10_quality was mutated")
    _write_quality_report(report_path, report)
    try:
        _verify_file_set(staging_path, EXPECTED_COMPLETE_FILES)
    except Exception:
        _remove_owned_file(report_path)
        raise
    return manifest


def _verify_m10_metric_counts(quality: M10QualityReportInput, streams: dict[str, list[dict[str, object]]]) -> None:
    relation_statuses = {key: sum(1 for row in streams["relations"] if row.get("resolution_status") == key) for key in ("resolved", "unresolved_without_jira_api", "deferred_mvp", "unresolved_target")}
    if quality.jira_metrics["relations_total"] != len(streams["relations"]) or quality.jira_metrics["resolved"] != relation_statuses["resolved"] or quality.jira_metrics["unresolved_without_jira_api"] != relation_statuses["unresolved_without_jira_api"] or quality.jira_metrics["deferred_mvp"] != relation_statuses["deferred_mvp"] or quality.jira_metrics["unresolved_target"] != relation_statuses["unresolved_target"]:
        raise ValueError("Jira relation count mismatch")
    if quality.acl_metrics["documents_total"] != len(streams["documents"]):
        raise ValueError("ACL document count mismatch")
    if quality.acl_metrics["documents_with_acl"] != len(streams["acl"]) or quality.acl_metrics["restricted_documents"] != sum(1 for row in streams["acl"] if row.get("is_restricted") is True) or quality.acl_metrics["default_deny_chunks"] != sum(1 for row in streams["chunks"] if row.get("acl_tags") == ["restricted:unresolved"]):
        raise ValueError("ACL count mismatch")
    media_statuses = {key: sum(1 for row in streams["media_assets"] if row.get("processing_status") == key) for key in ("parsed", "ocr", "summarized", "failed", "not_processed")}
    if quality.media_metrics["assets_total"] != len(streams["media_assets"]):
        raise ValueError("media count mismatch")
    if quality.media_metrics["processed"] != media_statuses["parsed"] + media_statuses["ocr"] + media_statuses["summarized"] or quality.media_metrics["failed"] != media_statuses["failed"] or quality.media_metrics["not_processed"] != media_statuses["not_processed"]:
        raise ValueError("media status count mismatch")
    if quality.symbol_metrics["symbols_total"] != len(streams["symbols"]) or quality.symbol_metrics["resolved"] != sum(1 for row in streams["symbols"] if row.get("chunk_id") is not None):
        raise ValueError("symbol count mismatch")
    sync_types = {key: sum(1 for row in streams["sync_state"] if row.get("entity_type") == source_type) for key, source_type in (("pages", "page"), ("attachments", "attachment"), ("files", "file"), ("repos", "repo"))}
    if quality.sync_metrics["rows_total"] != len(streams["sync_state"]) or quality.sync_metrics["active"] != sum(1 for row in streams["sync_state"] if row.get("status") == "active") or any(quality.sync_metrics[key] != sync_types[key] for key in ("pages", "attachments", "files", "repos")):
        raise ValueError("sync count mismatch")
    if quality.tombstone_metrics["rows_total"] != len(streams["tombstones"]):
        raise ValueError("tombstone count mismatch")


def _render_m10_quality_report(manifest: Mapping[str, object], quality: M10QualityReportInput) -> str:
    counts = quality.expected_counts
    lines = ["# Foundation Export Quality Report", "", "## Snapshot", "", f"- Export mode: `{manifest['export_mode']}`", f"- Dataset version: `{manifest['dataset_version']}`", f"- Generated at: `{manifest['generated_at']}`", f"- Schemas version: `{manifest['schemas_version']}`", "", "## Active Profiles", "", f"- Active profile: `{quality.active_profile}`", f"- Profile status: `{quality.profile_status}`", f"- Chunker version: `{quality.chunker_version}`", "", "## Record Counts", "", "| Record type | Count |", "|---|---:|"]
    lines.extend(f"| {key} | {counts[key]} |" for key in COUNT_KEYS)
    for title, field in (("Jira Relation Quality", "jira_metrics"), ("ACL Quality", "acl_metrics"), ("Media Quality", "media_metrics"), ("Symbol Quality", "symbol_metrics"), ("Sync State", "sync_metrics"), ("Tombstones", "tombstone_metrics"), ("Completion Checks", "completion_checks")):
        lines.extend(["", f"## {title}", ""])
        metric_mapping = getattr(quality, field)
        lines.extend(f"- {key}: {metric_mapping[key]}" for key in _M10_METRIC_KEYS[field])
    lines.extend(["", "## Publication State", "", "- Report completion: PENDING_AT_REPORT_COMPLETION", "- Final-directory verification: PENDING_AT_REPORT_COMPLETION", "- Post-publication acceptance: PENDING_AT_REPORT_COMPLETION", "", "## Scope", "", "- Confluence scope: present", f"- Git scope: {'present' if 'git' in quality.source_scopes else 'absent'}", ""])
    return "\n".join(lines)


class FullSnapshotStagingCompleter:
    """Add the human-readable sidecar to an existing M3D staging directory."""

    @staticmethod
    def complete(
        *,
        staging_path: Path,
        validator: FoundationSchemaValidator,
        one_page_quality: OnePageExportQualityReportInput | None = None,
        m10_quality: M10QualityReportInput | None = None,
    ) -> dict[str, object]:
        if m10_quality is not None:
            try:
                if type(staging_path) is not _CONCRETE_PATH_TYPE:
                    raise TypeError("m10_quality staging path must be Path")
                if one_page_quality is not None:
                    raise TypeError("one_page_quality is incompatible with m10_quality")
                if type(validator) is not FoundationSchemaValidator:
                    raise TypeError("m10_quality requires the shared FoundationSchemaValidator")
                _validate_m10_quality_input(m10_quality)
                return _complete_m10_quality(staging_path=staging_path, validator=validator, quality=m10_quality)
            except Exception:
                raise M10QualityCompletionError("m10_quality completion failed") from None
        if not staging_path.exists():
            raise FileNotFoundError(f"Staging path does not exist: {staging_path}")
        if not staging_path.is_dir():
            raise NotADirectoryError(f"Staging path is not a directory: {staging_path}")

        report_path = staging_path / QUALITY_REPORT_FILE_NAME
        if report_path.exists() or report_path.is_symlink():
            raise FileExistsError(f"Quality report already exists: {report_path}")

        _verify_file_set(staging_path, EXPECTED_MACHINE_FILES)
        manifest = _load_manifest(staging_path / "manifest.json")
        validator.validate_record("Manifest", manifest)
        _verify_full_snapshot_invariants(manifest)

        if one_page_quality is None:
            report = _render_quality_report(manifest)
        else:
            if not isinstance(one_page_quality, OnePageExportQualityReportInput):
                raise TypeError(
                    "one_page_quality expects OnePageExportQualityReportInput"
                )
            _verify_extended_completion_invariants(
                staging_path=staging_path,
                manifest=manifest,
                one_page_quality=one_page_quality,
                validator=validator,
            )
            report = _render_extended_quality_report(manifest, one_page_quality)

        _write_quality_report(report_path, report)
        try:
            _verify_file_set(staging_path, EXPECTED_COMPLETE_FILES)
        except Exception:
            _remove_owned_file(report_path)
            raise

        return manifest


def _load_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Manifest JSON must contain one object")
    return manifest


def _verify_full_snapshot_invariants(manifest: Mapping[str, object]) -> None:
    mode = manifest.get("export_mode")
    if mode not in {"full_snapshot", "delta"}:
        raise ValueError("Manifest export_mode is invalid")
    if mode == "full_snapshot" and "base_dataset_version" in manifest:
        raise ValueError("Full-snapshot Manifest must not contain base_dataset_version")
    if mode == "delta" and (type(manifest.get("base_dataset_version")) is not str or not manifest.get("base_dataset_version") or manifest.get("base_dataset_version") == manifest.get("dataset_version")):
        raise ValueError("Delta Manifest requires a distinct base_dataset_version")

    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise TypeError("Manifest counts must be a mapping")
    if set(counts) != set(COUNT_KEYS):
        raise ValueError(
            "Manifest counts must contain exactly the full-snapshot count keys"
        )

    for value in counts.values():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("Manifest counts values must be actual integers")
        if value < 0:
            raise ValueError("Manifest counts values must be non-negative")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> object:
    raise ValueError("non-finite JSON constant")


def _read_strict_jsonl_records(path: Path) -> list[dict[str, object]]:
    # Mirrors confluence_restriction_observation_sidecar.py's strict readback
    # technique (duplicate-key/non-finite-constant rejection); that module's
    # helpers are private and not importable, so this is a local mirror (R11).
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            raise ValueError(f"JSONL record in {path.name} must not be blank")
        record = json.loads(
            line,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_non_finite_constant,
        )
        if not isinstance(record, dict):
            raise TypeError(f"JSONL record in {path.name} must be an object")
        records.append(record)
    return records


def _verify_extended_completion_invariants(
    *,
    staging_path: Path,
    manifest: Mapping[str, object],
    one_page_quality: OnePageExportQualityReportInput,
    validator: FoundationSchemaValidator,
) -> None:
    quality_before = deepcopy(one_page_quality)

    manifest_counts = manifest.get("counts")
    if not isinstance(manifest_counts, Mapping):
        raise TypeError("Manifest counts must be a mapping")
    if _canonical_json(one_page_quality.expected_counts) != _canonical_json(
        dict(manifest_counts)
    ):
        raise ValueError(
            "one_page_quality.expected_counts do not match manifest counts"
        )

    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        records = _read_strict_jsonl_records(staging_path / file_name)
        if len(records) != manifest_counts[count_key]:
            raise ValueError(
                f"On-disk {file_name} record count does not match manifest counts"
            )
        for record in records:
            validator.validate_record(schema_name, record)

    for file_name in _DEFERRED_STREAM_FILE_NAMES:
        if (staging_path / file_name).stat().st_size != 0:
            raise ValueError(f"Deferred stream file must be empty: {file_name}")

    if one_page_quality != quality_before:
        raise RuntimeError("one_page_quality must not be mutated during completion")


def _bullet_list(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["- None"]
    return [f"- {value}" for value in values]


def _label(field_name: str) -> str:
    return field_name.replace("_", " ").capitalize()


def _metrics_table(metrics: Mapping[str, object], key_order: tuple[str, ...]) -> list[str]:
    lines = ["| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {key} | {metrics[key]} |" for key in key_order)
    return lines


def _render_quality_report(manifest: Mapping[str, object]) -> str:
    counts = manifest["counts"]
    if not isinstance(counts, Mapping):
        raise TypeError("Manifest counts must be a mapping")

    lines = [
        "# Foundation Export Quality Report",
        "",
        "## Snapshot",
        "",
        f"- Dataset version: `{manifest['dataset_version']}`",
        "- Export mode: `full_snapshot`",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Manifest schema version: `{manifest['schema_version']}`",
        f"- Schemas version: `{manifest['schemas_version']}`",
        f"- Chunker version: `{manifest['chunker_version']}`",
        f"- Config hash: `{manifest['config_hash']}`",
        "",
        "## Record Counts",
        "",
        "| Record type | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {counts[key]} |" for key in COUNT_KEYS)
    lines.extend(
        [
            "",
            "## Completion Checks",
            "",
            "- Machine-readable staging file set: PASS",
            "- Manifest JSON parsing: PASS",
            "- Manifest schema validation: PASS",
            "- Full-snapshot producer invariants: PASS",
            "",
            "## Scope",
            "",
            "This report summarizes Foundation export construction metadata only.",
            "",
            "It does not evaluate retrieval, embedding, indexing, semantic quality,",
            "hallucination, or answer quality.",
        ]
    )
    return "\n".join(lines) + "\n"


_ACL_QUALITY_COUNT_FIELDS: tuple[str, ...] = (
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


def _render_extended_quality_report(
    manifest: Mapping[str, object],
    one_page_quality: OnePageExportQualityReportInput,
) -> str:
    counts = manifest["counts"]
    if not isinstance(counts, Mapping):
        raise TypeError("Manifest counts must be a mapping")

    jira_quality = one_page_quality.jira_quality_observation
    acl_quality = one_page_quality.acl_quality_observation

    lines = [
        "# Foundation Export Quality Report",
        "",
        "## Snapshot",
        "",
        f"- Dataset version: `{manifest['dataset_version']}`",
        "- Export mode: `full_snapshot`",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Manifest schema version: `{manifest['schema_version']}`",
        f"- Schemas version: `{manifest['schemas_version']}`",
        f"- Config hash: `{manifest['config_hash']}`",
        "",
        "## Active Profiles",
        "",
        f"- Active profile: `{one_page_quality.active_profile}`",
        f"- Profile status: `{one_page_quality.profile_status}`",
        f"- Chunker version: `{one_page_quality.chunker_version}`",
        "",
        "## Record Counts",
        "",
        "| Record type | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {counts[key]} |" for key in COUNT_KEYS)

    lines.extend(["", "## Jira Relation Quality", "", "### Unique key-like candidates", ""])
    lines.extend(_bullet_list(jira_quality.unique_key_like_candidates))
    lines.extend(["", "### Allowlisted keys", ""])
    lines.extend(_bullet_list(jira_quality.allowlisted_keys))
    lines.extend(["", "### Outside-allowlist keys", ""])
    lines.extend(_bullet_list(jira_quality.outside_allowlist_keys))
    lines.append("")
    lines.extend(_metrics_table(one_page_quality.jira_metrics, JIRA_METRICS_KEY_ORDER))

    lines.extend(["", "## ACL Quality", ""])
    for field_name in _ACL_QUALITY_COUNT_FIELDS:
        value = getattr(acl_quality, field_name)
        lines.append(f"- {_label(field_name)}: {value}")
    lines.append(
        f"- Default deny applied: {'true' if acl_quality.default_deny_applied else 'false'}"
    )
    lines.append(
        "- Manual review required: "
        f"{'true' if acl_quality.manual_review_required else 'false'}"
    )
    lines.extend(["", "### Reason Codes", ""])
    lines.extend(_bullet_list(acl_quality.reason_codes))
    lines.append("")
    lines.extend(_metrics_table(one_page_quality.acl_metrics, ACL_METRICS_KEY_ORDER))

    lines.extend(
        [
            "",
            "## Empty and Deferred Streams",
            "",
            "media_assets: empty; deferred",
            "symbols: empty; deferred",
            "sync_state: empty; checkpoint persistence deferred to M7",
            "tombstones: empty; delta/deletion production deferred",
            "",
            "## Completion Checks",
            "",
            "- Machine-readable staging file set: PASS",
            "- Manifest JSON parsing: PASS",
            "- Manifest schema validation: PASS",
            "- Full-snapshot producer invariants: PASS",
            "- Manifest counts match emitted records: PASS",
            "- JSONL schema validation: PASS",
            "- Deferred streams are empty: PASS",
            "",
            "## Publication State",
            "",
            "- Final-directory verification: PENDING_AT_REPORT_COMPLETION",
            "- LATEST.txt verification: PENDING_AT_REPORT_COMPLETION",
            "- Post-publication acceptance: PENDING_AT_REPORT_COMPLETION",
            "",
            "## Scope",
            "",
            "This report summarizes Foundation export construction metadata only.",
            "",
            "It does not evaluate retrieval, embedding, indexing, semantic quality,",
            "hallucination, or answer quality.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_quality_report(path: Path, report: str) -> None:
    # R12 hardening: create-if-absent semantics rather than an unconditional
    # replace(), which is not no-clobber and leaves a check-then-act race
    # between the existence check above and the write below. Write the
    # content to a temp file, then hard-link it into place (os.link fails
    # with FileExistsError if the target already exists, without touching
    # it), then always remove the scratch temp file.
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(report)

        os.link(temp_path, path)
    finally:
        if temp_path is not None:
            _remove_owned_file(temp_path)


def _verify_file_set(staging_path: Path, expected_names: frozenset[str]) -> None:
    entries = list(staging_path.iterdir())
    actual_names = {entry.name for entry in entries}
    all_regular_files = all(
        entry.is_file() and not entry.is_symlink()
        for entry in entries
    )

    if actual_names != expected_names or not all_regular_files:
        raise RuntimeError(
            "Staging directory is incomplete or contains unexpected entries: "
            f"{sorted(actual_names)}"
        )


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove M3E-owned file: %s", path, exc_info=True)
