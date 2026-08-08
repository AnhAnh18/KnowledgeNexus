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
from types import MappingProxyType
from collections.abc import Mapping, Sequence

from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.domain.rules.snapshot_readback import (
    SnapshotReadbackError,
    validate_snapshot_streams,
)
from .full_snapshot_staging_writer import JSONL_FILE_SCHEMA_PAIRS


@dataclass(frozen=True)
class DeltaSnapshotReadback:
    manifest: Mapping[str, object]
    streams: Mapping[str, tuple[Mapping[str, object], ...]]
    digest: str

    def __post_init__(self) -> None:
        if type(self.manifest) is not dict or type(self.streams) is not dict:
            raise TypeError("readback mappings are invalid")
        frozen_manifest = _freeze_value(self.manifest)
        frozen_streams = {
            name: tuple(_freeze_value(row) for row in rows)
            for name, rows in self.streams.items()
        }
        object.__setattr__(self, "manifest", frozen_manifest)
        object.__setattr__(self, "streams", MappingProxyType(frozen_streams))


def _freeze_value(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_value(item) for item in value)
    if type(value) is tuple:
        return tuple(_freeze_value(item) for item in value)
    return value


def _strict_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def read_delta_snapshot(
    path: object,
    *,
    validator: FoundationSchemaValidator,
    prior_streams: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
) -> DeltaSnapshotReadback:
    if type(path) is not Path or not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise ValueError("invalid snapshot path")
    if type(validator) is not FoundationSchemaValidator:
        raise TypeError("invalid validator")
    expected_files = {"manifest.json", "quality_report.md"} | {file_name for file_name, _, _ in JSONL_FILE_SCHEMA_PAIRS}
    entries = tuple(path.iterdir())
    if {entry.name for entry in entries} != expected_files or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError("delta snapshot file set is invalid")
    manifest = _strict_json(path / "manifest.json")
    if type(manifest) is not dict or manifest.get("export_mode") != "delta":
        raise ValueError("snapshot is not a delta export")
    quality_report = path / "quality_report.md"
    if not quality_report.is_file() or quality_report.is_symlink() or not quality_report.read_bytes():
        raise ValueError("delta quality report is invalid")
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
    digest.update(b"quality_report.md\0")
    digest.update(quality_report.read_bytes())
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        stream_path = path / file_name
        records: list[dict[str, object]] = []
        for line in stream_path.read_text(encoding="utf-8").splitlines():
            if not line:
                raise ValueError("stream contains a blank line")
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
    try:
        validate_snapshot_streams(
            streams,
            export_mode="delta",
            prior_streams=prior_streams,
        )
    except SnapshotReadbackError:
        raise ValueError("delta cross-stream closure is invalid") from None
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
