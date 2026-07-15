"""Publish completed Foundation full-snapshot staging directories."""

from __future__ import annotations

import json
import logging
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import (
    COUNT_KEYS,
    EXPECTED_COMPLETE_FILES,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


logger = logging.getLogger(__name__)

DATASET_VERSION_PATTERN = re.compile(r"^v[0-9]{8}-[0-9]{6}-[0-9]{6}Z$")
LATEST_FILE_NAME = "LATEST.txt"


class FullSnapshotPublisher:
    """Publish one completed full snapshot and advertise it through LATEST."""

    @staticmethod
    def publish(
        *,
        staging_path: Path,
        dataset_root: Path,
        validator: FoundationSchemaValidator,
    ) -> Path:
        _verify_paths(staging_path=staging_path, dataset_root=dataset_root)
        _verify_completed_file_set(staging_path)

        manifest = _load_manifest(staging_path / "manifest.json")
        validator.validate_record("Manifest", manifest)
        dataset_version = _verify_publisher_invariants(manifest)

        final_path = dataset_root / dataset_version
        if final_path.parent.resolve() != dataset_root.resolve():
            raise ValueError("Final snapshot path must be a direct dataset-root child")
        if final_path.exists() or final_path.is_symlink():
            raise FileExistsError(f"Final snapshot already exists: {final_path}")

        latest_path = dataset_root / LATEST_FILE_NAME
        _verify_latest_path(latest_path)

        staging_path.rename(final_path)
        _write_latest(latest_path, dataset_version)
        return final_path


def _verify_paths(*, staging_path: Path, dataset_root: Path) -> None:
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root does not exist: {dataset_root}")
    if not dataset_root.is_dir():
        raise NotADirectoryError(f"Dataset root is not a directory: {dataset_root}")

    if staging_path.is_symlink():
        raise ValueError(f"Staging path must not be a symlink: {staging_path}")
    if not staging_path.exists():
        raise FileNotFoundError(f"Staging path does not exist: {staging_path}")
    if not staging_path.is_dir():
        raise NotADirectoryError(f"Staging path is not a directory: {staging_path}")
    if staging_path.parent.resolve() != dataset_root.resolve():
        raise ValueError("Staging path must be a direct child of dataset root")


def _verify_completed_file_set(staging_path: Path) -> None:
    entries = list(staging_path.iterdir())
    actual_names = {entry.name for entry in entries}
    all_regular_files = all(
        entry.is_file() and not entry.is_symlink()
        for entry in entries
    )

    if actual_names != EXPECTED_COMPLETE_FILES or not all_regular_files:
        raise RuntimeError(
            "Completed staging directory is incomplete or contains unexpected "
            f"entries: {sorted(actual_names)}"
        )


def _load_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Manifest JSON must contain one object")
    return manifest


def _verify_publisher_invariants(manifest: Mapping[str, object]) -> str:
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

    dataset_version = manifest.get("dataset_version")
    if not isinstance(dataset_version, str):
        raise TypeError("Manifest dataset_version must be a string")
    if DATASET_VERSION_PATTERN.fullmatch(dataset_version) is None:
        raise ValueError(
            "Manifest dataset_version must match "
            "vYYYYMMDD-HHMMSS-ffffffZ"
        )
    return dataset_version


def _verify_latest_path(latest_path: Path) -> None:
    if latest_path.is_symlink():
        raise FileExistsError(f"LATEST path must not be a symlink: {latest_path}")
    if latest_path.exists() and not latest_path.is_file():
        raise FileExistsError(
            f"LATEST path must be a regular file: {latest_path}"
        )


def _write_latest(latest_path: Path, dataset_version: str) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=latest_path.parent,
            prefix=f".{latest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(f"{dataset_version}\n")

        temp_path.replace(latest_path)
    except Exception:
        if temp_path is not None:
            _remove_owned_temp_file(temp_path)
        raise


def _remove_owned_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "Failed to remove M3F-owned temporary file: %s",
            path,
            exc_info=True,
        )
