"""Complete Foundation full-snapshot staging with a quality report."""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping
from pathlib import Path

from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import (
    EXPECTED_MACHINE_FILES,
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


class FullSnapshotStagingCompleter:
    """Add the human-readable sidecar to an existing M3D staging directory."""

    @staticmethod
    def complete(
        *,
        staging_path: Path,
        validator: FoundationSchemaValidator,
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

        report = _render_quality_report(manifest)
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


def _write_quality_report(path: Path, report: str) -> None:
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

        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            _remove_owned_file(temp_path)
        raise


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
