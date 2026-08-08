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
_CONCRETE_PATH_TYPE = type(Path())

_TOMBSTONE_TARGET_GRAMMARS: dict[str, re.Pattern[str] | None] = {
    "document": re.compile(r"^(?:confluence:page:[^\s:]+|git:file:[^\s]+)$"),
    "chunk": re.compile(r"^chunk:(?:confluence|git):[0-9a-f]{16}(?:-[0-9]+)?$"),
    "media": re.compile(r"^confluence:attachment:[^\s:]+$"),
    "relation": re.compile(r"^rel:[0-9a-f]{16}$"),
    "acl": re.compile(r"^acl:(?:confluence|repo):[^\s]+$"),
    # Symbol IDs are generated as repo:branch:file:qualified_name.  Their
    # source is pinned below by the matching base symbol row.
    "symbol": None,
}
_TOMBSTONE_ENTITY_TYPES = frozenset(_TOMBSTONE_TARGET_GRAMMARS)


def _validate_publish_inputs(*, staging_path: object, dataset_root: object, validator: object) -> None:
    """Reject forged runtime types before any path or validator access."""
    if type(staging_path) is not _CONCRETE_PATH_TYPE or type(dataset_root) is not _CONCRETE_PATH_TYPE:
        raise TypeError("publish paths must be concrete Path values")
    if type(validator) is not FoundationSchemaValidator:
        raise TypeError("publish validator is invalid")


class FullSnapshotPublisher:
    """Publish one completed full snapshot and advertise it through LATEST."""

    @staticmethod
    def publish(
        *,
        staging_path: Path,
        dataset_root: Path,
        validator: FoundationSchemaValidator,
    ) -> Path:
        _validate_publish_inputs(staging_path=staging_path, dataset_root=dataset_root, validator=validator)
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
    if not dataset_root.is_absolute() or dataset_root.is_symlink():
        raise ValueError("Dataset root must be an absolute regular directory")
    if not staging_path.is_absolute():
        raise ValueError("Staging path must be absolute")
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
    manifest = _strict_json_loads(path.read_text(encoding="utf-8"))
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


def _verify_delta_publisher_invariants(
    manifest: Mapping[str, object],
    *,
    dataset_root: Path,
    staging_path: Path | None = None,
    validator: FoundationSchemaValidator | None = None,
) -> str:
    """Validate the version chain before publishing a delta directory.

    Delta staging is completed by the M10 completer, but publication still
    needs an independent guard that the referenced base is a local, regular
    snapshot directory.  This prevents a malformed manifest from advertising
    a delta detached from the prior dataset.
    """
    if manifest.get("export_mode") != "delta":
        raise ValueError("Manifest export_mode must be 'delta'")
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise TypeError("Manifest counts must be a mapping")
    if set(counts) != set(COUNT_KEYS):
        raise ValueError("Manifest counts must contain exactly the full-snapshot count keys")
    for value in counts.values():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("Manifest counts values must be actual integers")
        if value < 0:
            raise ValueError("Manifest counts values must be non-negative")

    dataset_version = manifest.get("dataset_version")
    base_version = manifest.get("base_dataset_version")
    if not isinstance(dataset_version, str) or DATASET_VERSION_PATTERN.fullmatch(dataset_version) is None:
        raise ValueError("Manifest dataset_version is invalid")
    if not isinstance(base_version, str) or DATASET_VERSION_PATTERN.fullmatch(base_version) is None or base_version == dataset_version:
        raise ValueError("Delta Manifest requires a distinct base_dataset_version")
    base_path = dataset_root / base_version
    if base_path.parent != dataset_root or base_path.is_symlink() or not base_path.is_dir():
        raise FileNotFoundError("Delta base snapshot is unavailable")
    # A non-empty tombstone stream must be anchored to entities actually
    # present in the referenced base. Keep the historical empty-delta seam
    # usable for callers that only exercise publication mechanics.
    if staging_path is not None:
        tombstones_path = staging_path / "tombstones.jsonl"
        tombstone_records = _read_jsonl_records(tombstones_path)
        if tombstone_records:
            if validator is None or type(validator) is not FoundationSchemaValidator:
                raise TypeError("delta validator is invalid")
            base_manifest_path = base_path / "manifest.json"
            if not base_manifest_path.is_file() or base_manifest_path.is_symlink():
                raise FileNotFoundError("Delta base manifest is unavailable")
            base_manifest = _load_manifest(base_manifest_path)
            validator.validate_record("Manifest", base_manifest)
            if base_manifest.get("dataset_version") != base_version:
                raise ValueError("Delta base manifest identity is invalid")
            stream_files = {
                "document": "documents.jsonl",
                "chunk": "chunks.jsonl",
                "relation": "relations.jsonl",
                "acl": "acl.jsonl",
                "media": "media_assets.jsonl",
                "symbol": "symbols.jsonl",
            }
            prior_ids: dict[str, set[str]] = {}
            prior_rows: dict[tuple[str, str], dict[str, object]] = {}
            for entity_type, filename in stream_files.items():
                path = base_path / filename
                if not path.is_file() or path.is_symlink():
                    raise FileNotFoundError("Delta base stream is unavailable")
                rows = _read_jsonl_records(path)
                identity_field = {
                    "document": "document_id", "chunk": "chunk_id", "relation": "relation_id",
                    "acl": "acl_id", "media": "media_id", "symbol": "symbol_id",
                }[entity_type]
                prior_ids[entity_type] = set()
                for row in rows:
                    identity = row.get(identity_field)
                    if type(identity) is str:
                        prior_ids[entity_type].add(identity)
                        prior_rows[(entity_type, identity)] = row
            seen: set[str] = set()
            for record in tombstone_records:
                validator.validate_record("TombstoneRecord", record)
                tombstone_id = record.get("tombstone_id")
                entity_type = record.get("entity_type")
                entity_id = record.get("entity_id")
                if (
                    type(tombstone_id) is not str
                    or tombstone_id in seen
                    or entity_type not in prior_ids
                    or type(entity_id) is not str
                    or entity_id not in prior_ids[entity_type]
                ):
                    raise ValueError("Delta tombstone target is absent from base")
                _verify_tombstone_target_ownership(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    base_row=prior_rows[(entity_type, entity_id)],
                )
                if record.get("dataset_version") != dataset_version:
                    raise ValueError("Delta tombstone provenance is invalid")
                seen.add(tombstone_id)
    return dataset_version


def _read_jsonl_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            raise ValueError("JSONL stream contains a blank line")
        value = _strict_json_loads(line)
        if type(value) is not dict:
            raise TypeError("JSONL stream record must be an object")
        records.append(value)
    return records


def _strict_json_loads(raw: str) -> object:
    """Parse JSON without accepting duplicate keys or non-finite constants."""
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        raw,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def _verify_tombstone_target_ownership(
    *,
    entity_type: object,
    entity_id: object,
    base_row: Mapping[str, object],
) -> None:
    """Bind a delta tombstone to the source grammar of its prior row."""
    if type(entity_type) is not str or entity_type not in _TOMBSTONE_ENTITY_TYPES:
        raise ValueError("Delta tombstone entity type is invalid")
    if type(entity_id) is not str:
        raise ValueError("Delta tombstone entity identity is invalid")
    grammar = _TOMBSTONE_TARGET_GRAMMARS[entity_type]
    if grammar is not None and grammar.fullmatch(entity_id) is None:
        raise ValueError("Delta tombstone source ownership is invalid")

    source_system = base_row.get("source_system")
    if entity_type in {"document", "chunk", "acl"}:
        if source_system not in {"confluence", "git"}:
            # ACL rows use source_system; documents/chunks do as well.
            raise ValueError("Delta tombstone source provenance is invalid")
        expected = "git" if entity_id.startswith(("git:", "chunk:git:", "acl:repo:")) else "confluence"
        if source_system != expected:
            raise ValueError("Delta tombstone source ownership is invalid")
    elif entity_type == "media":
        if source_system not in (None, "confluence"):
            raise ValueError("Delta tombstone source ownership is invalid")
    elif entity_type == "relation":
        # RelationRecord has no source_system; source_id must point at the
        # source-owned document/chunk in the already validated base.
        source_id = base_row.get("source_id")
        if type(source_id) is not str or not source_id.startswith(("confluence:", "chunk:confluence:")):
            raise ValueError("Delta tombstone source provenance is invalid")
    else:  # symbol
        if source_system not in (None, "git"):
            raise ValueError("Delta tombstone source ownership is invalid")
        if not entity_id or entity_id.startswith(("confluence:", "git:file:", "chunk:", "acl:", "rel:")):
            raise ValueError("Delta tombstone source ownership is invalid")
        if len(entity_id.split(":")) < 3 or any(not part for part in entity_id.split(":")):
            raise ValueError("Delta tombstone source ownership is invalid")
        repo = base_row.get("repo")
        branch = base_row.get("branch")
        if type(repo) is not str or type(branch) is not str or entity_id.split(":", 2)[:2] != [repo, branch]:
            raise ValueError("Delta tombstone source ownership is invalid")


class DeltaSnapshotPublisher:
    """Publish one completed delta snapshot using the same atomic M3 seam."""

    @staticmethod
    def publish(*, staging_path: Path, dataset_root: Path, validator: FoundationSchemaValidator) -> Path:
        _validate_publish_inputs(staging_path=staging_path, dataset_root=dataset_root, validator=validator)
        _verify_paths(staging_path=staging_path, dataset_root=dataset_root)
        _verify_completed_file_set(staging_path)
        manifest = _load_manifest(staging_path / "manifest.json")
        validator.validate_record("Manifest", manifest)
        dataset_version = _verify_delta_publisher_invariants(manifest, dataset_root=dataset_root, staging_path=staging_path, validator=validator)
        final_path = dataset_root / dataset_version
        if final_path.parent.resolve() != dataset_root.resolve():
            raise ValueError("Final snapshot path must be a direct dataset-root child")
        if final_path.exists() or final_path.is_symlink():
            raise FileExistsError(f"Final snapshot already exists: {final_path}")
        latest_path = dataset_root / LATEST_FILE_NAME
        _verify_latest_path(latest_path)
        staging_path.rename(final_path)
        try:
            _write_latest(latest_path, dataset_version)
        except Exception:
            # Keep the staging/final transition recoverable if pointer write fails.
            try:
                final_path.rename(staging_path)
            except OSError:
                pass
            raise
        return final_path


class M10SnapshotPublisher:
    """Dispatch full and delta publications without weakening either gate."""

    @staticmethod
    def publish(*, staging_path: Path, dataset_root: Path, validator: FoundationSchemaValidator) -> Path:
        _validate_publish_inputs(staging_path=staging_path, dataset_root=dataset_root, validator=validator)
        _verify_paths(staging_path=staging_path, dataset_root=dataset_root)
        manifest = _load_manifest(staging_path / "manifest.json")
        mode = manifest.get("export_mode")
        if mode == "full_snapshot":
            return FullSnapshotPublisher.publish(staging_path=staging_path, dataset_root=dataset_root, validator=validator)
        if mode == "delta":
            return DeltaSnapshotPublisher.publish(staging_path=staging_path, dataset_root=dataset_root, validator=validator)
        raise ValueError("Manifest export_mode is invalid")


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
