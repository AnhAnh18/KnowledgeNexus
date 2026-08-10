"""Strict readback for published delta snapshots.

The reader validates bytes without mutating records and returns an immutable
in-memory view suitable for a downstream publication gate.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from .full_snapshot_staging_writer import JSONL_FILE_SCHEMA_PAIRS


@dataclass(frozen=True)
class DeltaSnapshotReadback:
    manifest: dict[str, object]
    streams: dict[str, tuple[dict[str, object], ...]]
    digest: str


def _strict_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def read_delta_snapshot(path: object, *, validator: FoundationSchemaValidator) -> DeltaSnapshotReadback:
    if type(path) is not Path or not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise ValueError("invalid snapshot path")
    if type(validator) is not FoundationSchemaValidator:
        raise TypeError("invalid validator")
    expected_files = {"manifest.json"} | {file_name for file_name, _, _ in JSONL_FILE_SCHEMA_PAIRS}
    entries = tuple(path.iterdir())
    if {entry.name for entry in entries} != expected_files or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError("delta snapshot file set is invalid")
    manifest = _strict_json(path / "manifest.json")
    if type(manifest) is not dict or manifest.get("export_mode") != "delta":
        raise ValueError("snapshot is not a delta export")
    base = manifest.get("base_dataset_version")
    dataset = manifest.get("dataset_version")
    if type(base) is not str or not base or type(dataset) is not str or not dataset or base == dataset:
        raise ValueError("delta manifest version chain is invalid")
    validator_copy = deepcopy(manifest)
    validator.validate_record("Manifest", validator_copy)
    if validator_copy != manifest:
        raise ValueError("validator mutated manifest")
    counts = manifest.get("counts")
    if type(counts) is not dict or set(counts) != {key for _, key, _ in JSONL_FILE_SCHEMA_PAIRS} or any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("delta counts are invalid")
    streams: dict[str, tuple[dict[str, object], ...]] = {}
    digest = hashlib.sha256()
    digest.update(b"manifest.json\0")
    digest.update((path / "manifest.json").read_bytes())
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        stream_path = path / file_name
        records: list[dict[str, object]] = []
        for line in stream_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            value = _strict_json_line(line)
            if type(value) is not dict:
                raise ValueError("stream record is invalid")
            checked = deepcopy(value)
            validator.validate_record(schema_name, checked)
            if checked != value:
                raise ValueError("validator mutated stream record")
            records.append(deepcopy(value))
        if len(records) != counts[count_key]:
            raise ValueError("stream count mismatch")
        streams[count_key] = tuple(records)
        digest.update(file_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(stream_path.read_bytes())
    return DeltaSnapshotReadback(manifest=deepcopy(manifest), streams=streams, digest=digest.hexdigest())


def _strict_json_line(line: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(line, object_pairs_hook=reject_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


__all__ = ["DeltaSnapshotReadback", "read_delta_snapshot"]
