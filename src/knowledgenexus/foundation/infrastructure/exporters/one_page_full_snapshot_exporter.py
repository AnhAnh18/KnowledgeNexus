"""Orchestrate the existing M3 writer/completer/publisher for one trusted
``OnePageExportProjection`` (spec §7, M6G-C).

This module reuses the four existing M3 APIs exactly as they exist today
(``DatasetVersionGenerator``, ``FullSnapshotStagingWriter``,
``FullSnapshotStagingCompleter``, ``FullSnapshotPublisher``) -- it does not
build a parallel writer, publisher, pointer writer, or version generator.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.project_one_page_export import (
    OnePageExportProjection,
)
from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
    OnePageExportCauseFamily,
    OnePageExportConfigurationError,
    OnePageExportStage,
)
from knowledgenexus.foundation.domain.models.one_page_export_snapshot import (
    OnePageExportAcceptanceResult,
    OnePageExportQualityReportInput,
    OnePageFullSnapshotExportResult,
)
from knowledgenexus.foundation.domain.rules.dataset_version_generator import (
    DatasetVersionGenerator,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher import (
    LATEST_FILE_NAME,
    FullSnapshotPublisher,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import (
    FullSnapshotStagingCompleter,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import (
    JSONL_FILE_SCHEMA_PAIRS,
    FullSnapshotStagingWriter,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)

_EXPORT_ERROR_CATEGORIES = frozenset(
    {
        "export_projection",
        "export_staging",
        "export_completion",
        "export_publication",
        "export_acceptance",
    }
)

_DEFERRED_STREAM_NAMES: tuple[str, ...] = ("media_assets", "symbols", "sync_state", "tombstones")
_PUBLISHED_FILE_NAMES = frozenset(
    {name for name, _, _ in JSONL_FILE_SCHEMA_PAIRS} | {"manifest.json", "quality_report.md"}
)

# Reuses the exact strict RFC3339 semantics already approved in the M6C/M6E/
# M6F application layer (precedent: materialize_confluence_acl.py). Deliberately
# duplicated here rather than refactored into a shared timestamp helper, which
# is out of M6G-C scope (R13).
_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.[0-9]+)?"
    r"(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})$"
)


def _is_rfc3339_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _RFC3339.fullmatch(value)
    if match is None:
        return False
    zone = match.group("zone")
    if zone != "Z":
        hours, minutes = (int(part) for part in zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


class OnePageFullSnapshotExportError(Exception):
    """A sanitized M6G-C export failure. ``str(error)`` is only the category."""

    def __init__(self, category: str) -> None:
        if category not in _EXPORT_ERROR_CATEGORIES:
            raise ValueError("category is not a recognized export failure category")
        self.category = category
        super().__init__(category)


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


def _read_strict_manifest(path: Path) -> dict[str, object]:
    # Mirrors confluence_restriction_observation_sidecar.py's strict readback
    # technique; that module's helpers are private and not importable, so
    # this is a local mirror (R11).
    text = path.read_text(encoding="utf-8")
    manifest = json.loads(
        text,
        object_pairs_hook=_reject_duplicate_object_keys,
        parse_constant=_reject_non_finite_constant,
    )
    if not isinstance(manifest, dict):
        raise TypeError("Manifest JSON must contain one object")
    return manifest


def _read_strict_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    text = path.read_text(encoding="utf-8")
    records: list[dict[str, object]] = []
    for line in text.splitlines():
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
    return tuple(records)


class OnePageFullSnapshotExporter:
    """Consume one trusted projection and export it exactly once via M3."""

    @staticmethod
    def export(
        *,
        projection: OnePageExportProjection,
        generated_at: str,
        export_root: Path,
        validator: FoundationSchemaValidator,
    ) -> OnePageFullSnapshotExportResult:
        # Step 1: stage-mapped configuration validation.
        # Stage: export_input_validation
        if not isinstance(projection, OnePageExportProjection):
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.EXPORT_INPUT_VALIDATION,
                cause_family=OnePageExportCauseFamily.TYPE_ERROR,
            )

        # Stage: generated_at_validation
        if not isinstance(generated_at, str):
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.GENERATED_AT_VALIDATION,
                cause_family=OnePageExportCauseFamily.TYPE_ERROR,
            )
        if not _is_rfc3339_timestamp(generated_at):
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.GENERATED_AT_VALIDATION,
                cause_family=OnePageExportCauseFamily.VALUE_ERROR,
            )
        try:
            parsed_generated_at = datetime.fromisoformat(
                generated_at.replace("Z", "+00:00")
            )
        except ValueError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.GENERATED_AT_VALIDATION,
                cause_family=OnePageExportCauseFamily.VALUE_ERROR,
            ) from None

        # Stage: dataset_root_validation
        if not isinstance(export_root, Path):
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_ROOT_VALIDATION,
                cause_family=OnePageExportCauseFamily.TYPE_ERROR,
            )
        dataset_root = export_root / ONE_PAGE_DATASET_NAME
        try:
            if dataset_root.is_symlink():
                raise ValueError("Dataset root must not be a symlink")
            if not dataset_root.exists():
                raise FileNotFoundError(f"Dataset root does not exist: {dataset_root}")
            if not dataset_root.is_dir():
                raise NotADirectoryError(f"Dataset root is not a directory: {dataset_root}")
        except ValueError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_ROOT_VALIDATION,
                cause_family=OnePageExportCauseFamily.VALUE_ERROR,
            ) from None
        except OSError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_ROOT_VALIDATION,
                cause_family=OnePageExportCauseFamily.IO_ERROR,
            ) from None

        # Step 2: entry snapshot (R8). Every stream handed to the writer is a
        # fresh deep copy -- never a direct reference into the caller's
        # projection tuples.
        entry_snapshot = deepcopy(projection)
        documents = tuple(deepcopy(dict(record)) for record in projection.documents)
        chunks = tuple(deepcopy(dict(record)) for record in projection.chunks)
        relations = tuple(deepcopy(dict(record)) for record in projection.relations)
        acl = tuple(deepcopy(dict(record)) for record in projection.acl)
        media_assets = tuple(deepcopy(dict(record)) for record in projection.media_assets)
        symbols = tuple(deepcopy(dict(record)) for record in projection.symbols)
        sync_state = tuple(deepcopy(dict(record)) for record in projection.sync_state)
        tombstones = tuple(deepcopy(dict(record)) for record in projection.tombstones)
        source_scopes = deepcopy(projection.source_scopes)

        # Step 3: expected counts + quality input (R9). Nothing is written to
        # disk yet; any failure here is export_projection.
        try:
            expected_counts = {
                "documents": len(documents),
                "chunks": len(chunks),
                "relations": len(relations),
                "acl": len(acl),
                "media_assets": len(media_assets),
                "symbols": len(symbols),
                "sync_state": len(sync_state),
                "tombstones": len(tombstones),
            }
            quality_input = OnePageExportQualityReportInput(
                active_profile=projection.active_profile,
                profile_status=projection.profile_status,
                chunker_version=projection.chunker_version,
                expected_counts=expected_counts,
                jira_quality_observation=projection.jira_quality_observation,
                jira_metrics=projection.jira_metrics,
                acl_quality_observation=projection.acl_quality_observation,
                acl_metrics=projection.acl_metrics,
            )
        except (TypeError, ValueError):
            raise OnePageFullSnapshotExportError("export_projection") from None

        # Step 4: dataset_version. Deterministic given generated_at; never
        # reads the system clock.
        # Stage: dataset_version_generation
        try:
            dataset_version = DatasetVersionGenerator.generate(
                instant=parsed_generated_at
            )
        except TypeError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_VERSION_GENERATION,
                cause_family=OnePageExportCauseFamily.TYPE_ERROR,
            ) from None
        except ValueError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_VERSION_GENERATION,
                cause_family=OnePageExportCauseFamily.VALUE_ERROR,
            ) from None
        except OSError:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_VERSION_GENERATION,
                cause_family=OnePageExportCauseFamily.IO_ERROR,
            ) from None
        except Exception:
            raise OnePageExportConfigurationError(
                stage=OnePageExportStage.DATASET_VERSION_GENERATION,
                cause_family=OnePageExportCauseFamily.UNEXPECTED_ERROR,
            ) from None

        # Step 5: staging_path. No caller-supplied path; no pre-create.
        staging_path = dataset_root / f".staging-{dataset_version}"

        # Step 6: FullSnapshotStagingWriter.
        try:
            manifest = FullSnapshotStagingWriter.write(
                staging_path=staging_path,
                validator=validator,
                dataset_version=dataset_version,
                generated_at=generated_at,
                config_hash=projection.config_hash,
                chunker_version=projection.chunker_version,
                schemas_version=projection.schemas_version,
                documents=documents,
                chunks=chunks,
                relations=relations,
                acl=acl,
                media_assets=media_assets,
                symbols=symbols,
                sync_state=sync_state,
                tombstones=tombstones,
                source_scopes=source_scopes,
            )
            if _canonical_json(manifest.get("counts")) != _canonical_json(
                expected_counts
            ):
                raise ValueError("Writer manifest counts do not match expected counts")
        except Exception:
            raise OnePageFullSnapshotExportError("export_staging") from None

        # Step 7: FullSnapshotStagingCompleter (extended). Snapshot the
        # quality report bytes immediately, before publication moves the
        # staging directory.
        try:
            completed_manifest = FullSnapshotStagingCompleter.complete(
                staging_path=staging_path,
                validator=validator,
                one_page_quality=quality_input,
            )
            if _canonical_json(completed_manifest) != _canonical_json(manifest):
                raise ValueError("Completed manifest differs from staged manifest")
            quality_report_snapshot = (staging_path / "quality_report.md").read_bytes()
        except Exception:
            raise OnePageFullSnapshotExportError("export_completion") from None

        # Step 8: FullSnapshotPublisher.
        try:
            final_path = FullSnapshotPublisher.publish(
                staging_path=staging_path,
                dataset_root=dataset_root,
                validator=validator,
            )
        except Exception:
            raise OnePageFullSnapshotExportError("export_publication") from None

        # Step 9: post-publication acceptance. No rollback of the
        # now-published snapshot on any failure here.
        try:
            acceptance = _verify_post_publication_acceptance(
                final_path=final_path,
                dataset_root=dataset_root,
                dataset_version=dataset_version,
                generated_at=generated_at,
                expected_counts=expected_counts,
                projection=projection,
                quality_report_snapshot=quality_report_snapshot,
                validator=validator,
            )
            if projection != entry_snapshot:
                raise ValueError("projection was mutated during export")
        except Exception:
            raise OnePageFullSnapshotExportError("export_acceptance") from None

        return OnePageFullSnapshotExportResult(
            dataset_version=dataset_version,
            final_path=final_path,
            manifest=completed_manifest,
            acceptance=acceptance,
        )


def _verify_post_publication_acceptance(
    *,
    final_path: Path,
    dataset_root: Path,
    dataset_version: str,
    generated_at: str,
    expected_counts: Mapping[str, int],
    projection: OnePageExportProjection,
    quality_report_snapshot: bytes,
    validator: FoundationSchemaValidator,
) -> OnePageExportAcceptanceResult:
    expected_final_path = dataset_root / dataset_version
    if final_path != expected_final_path:
        raise ValueError("final_path does not match dataset_root/dataset_version")
    if final_path.is_symlink() or not final_path.is_dir():
        raise ValueError("Published snapshot path must be a plain directory")

    entries = list(final_path.iterdir())
    actual_names = {entry.name for entry in entries}
    final_file_set_valid = actual_names == _PUBLISHED_FILE_NAMES and all(
        entry.is_file() and not entry.is_symlink() for entry in entries
    )
    if not final_file_set_valid:
        raise ValueError("Published snapshot file set is invalid")

    manifest = _read_strict_manifest(final_path / "manifest.json")
    validator.validate_record("Manifest", manifest)
    manifest_schema_valid = True

    manifest_version_matches_directory = (
        manifest.get("dataset_version") == dataset_version == final_path.name
    )
    if not manifest_version_matches_directory:
        raise ValueError("Manifest dataset_version does not match directory name")

    expected_metadata = {
        "generated_at": generated_at,
        "config_hash": projection.config_hash,
        "chunker_version": projection.chunker_version,
        "schemas_version": projection.schemas_version,
        "source_scopes": projection.source_scopes,
    }
    actual_metadata = {
        "generated_at": manifest.get("generated_at"),
        "config_hash": manifest.get("config_hash"),
        "chunker_version": manifest.get("chunker_version"),
        "schemas_version": manifest.get("schemas_version"),
        "source_scopes": manifest.get("source_scopes"),
    }
    manifest_metadata_matches_projection = _canonical_json(
        actual_metadata
    ) == _canonical_json(expected_metadata)
    if not manifest_metadata_matches_projection:
        raise ValueError("Manifest metadata does not match projection")

    manifest_counts_match = _canonical_json(manifest.get("counts")) == _canonical_json(
        dict(expected_counts)
    )
    if not manifest_counts_match:
        raise ValueError("Manifest counts do not match expected counts")

    projection_streams = {
        "documents": projection.documents,
        "chunks": projection.chunks,
        "relations": projection.relations,
        "acl": projection.acl,
        "media_assets": projection.media_assets,
        "symbols": projection.symbols,
        "sync_state": projection.sync_state,
        "tombstones": projection.tombstones,
    }
    records_match_projection = True
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        records = _read_strict_jsonl(final_path / file_name)
        for record in records:
            validator.validate_record(schema_name, record)
        expected_records = projection_streams[count_key]
        if len(records) != len(expected_records) or _canonical_json(
            list(records)
        ) != _canonical_json(list(expected_records)):
            records_match_projection = False
            break
    if not records_match_projection:
        raise ValueError("Published records do not match projection source")

    deferred_streams_empty = all(
        (final_path / f"{name}.jsonl").stat().st_size == 0
        for name in _DEFERRED_STREAM_NAMES
    )
    if not deferred_streams_empty:
        raise ValueError("Deferred stream files are not empty")

    quality_report_bytes = (final_path / "quality_report.md").read_bytes()
    quality_report_unchanged_after_publication = (
        quality_report_bytes == quality_report_snapshot
        and b"PENDING_AT_REPORT_COMPLETION" in quality_report_bytes
    )
    if not quality_report_unchanged_after_publication:
        raise ValueError("Quality report changed after publication")

    latest_path = dataset_root / LATEST_FILE_NAME
    latest_pointer_valid = (
        latest_path.exists()
        and latest_path.is_file()
        and not latest_path.is_symlink()
        and latest_path.read_bytes() == f"{dataset_version}\n".encode("utf-8")
    )
    if not latest_pointer_valid:
        raise ValueError("LATEST.txt is invalid")

    return OnePageExportAcceptanceResult(
        final_file_set_valid=final_file_set_valid,
        manifest_schema_valid=manifest_schema_valid,
        manifest_version_matches_directory=manifest_version_matches_directory,
        manifest_metadata_matches_projection=manifest_metadata_matches_projection,
        manifest_counts_match=manifest_counts_match,
        records_match_projection=records_match_projection,
        deferred_streams_empty=deferred_streams_empty,
        quality_report_unchanged_after_publication=quality_report_unchanged_after_publication,
        latest_pointer_valid=latest_pointer_valid,
    )
