"""Complete Foundation full-snapshot staging with a quality report."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    ACL_METRICS_KEY_ORDER,
    JIRA_METRICS_KEY_ORDER,
    OnePageExportQualityReportInput,
)
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

_DEFERRED_STREAM_FILE_NAMES: tuple[str, ...] = (
    "media_assets.jsonl",
    "symbols.jsonl",
    "sync_state.jsonl",
    "tombstones.jsonl",
)


class FullSnapshotStagingCompleter:
    """Add the human-readable sidecar to an existing M3D staging directory."""

    @staticmethod
    def complete(
        *,
        staging_path: Path,
        validator: FoundationSchemaValidator,
        one_page_quality: OnePageExportQualityReportInput | None = None,
    ) -> dict[str, object]:
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
    if manifest.get("export_mode") != "full_snapshot":
        raise ValueError("Manifest export_mode must be 'full_snapshot'")
    if "base_dataset_version" in manifest:
        raise ValueError(
            "Full-snapshot Manifest must not contain base_dataset_version"
        )

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
            continue
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
