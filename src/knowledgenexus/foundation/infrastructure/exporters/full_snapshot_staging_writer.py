"""Build machine-readable Foundation full-snapshot staging directories."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from knowledgenexus.foundation.domain.records import ManifestRecordBuilder
from knowledgenexus.foundation.infrastructure.exporters.jsonl_record_writer import (
    JsonlRecordWriter,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


JSONL_FILE_SCHEMA_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("documents.jsonl", "documents", "CanonicalDocument"),
    ("chunks.jsonl", "chunks", "ChunkRecord"),
    ("relations.jsonl", "relations", "RelationRecord"),
    ("acl.jsonl", "acl", "ACLRecord"),
    ("media_assets.jsonl", "media_assets", "MediaAsset"),
    ("symbols.jsonl", "symbols", "SymbolRecord"),
    ("sync_state.jsonl", "sync_state", "SyncStateRecord"),
    ("tombstones.jsonl", "tombstones", "TombstoneRecord"),
)

EXPECTED_MACHINE_FILES = frozenset(
    [file_name for file_name, _, _ in JSONL_FILE_SCHEMA_PAIRS] + ["manifest.json"]
)


class FullSnapshotStagingWriter:
    """Write a validated machine-readable full-snapshot staging directory."""

    @staticmethod
    def write(
        *,
        staging_path: Path,
        validator: FoundationSchemaValidator,
        dataset_version: str,
        generated_at: str,
        config_hash: str,
        chunker_version: str,
        schemas_version: str,
        documents: Iterable[Mapping[str, object]],
        chunks: Iterable[Mapping[str, object]],
        relations: Iterable[Mapping[str, object]],
        acl: Iterable[Mapping[str, object]],
        media_assets: Iterable[Mapping[str, object]],
        symbols: Iterable[Mapping[str, object]],
        sync_state: Iterable[Mapping[str, object]],
        tombstones: Iterable[Mapping[str, object]],
        source_scopes: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if staging_path.exists():
            raise FileExistsError(f"Staging path already exists: {staging_path}")
        if not staging_path.parent.is_dir():
            raise FileNotFoundError(
                f"Staging parent directory does not exist: {staging_path.parent}"
            )

        staging_path.mkdir()
        try:
            counts = _write_jsonl_files(
                staging_path=staging_path,
                validator=validator,
                documents=documents,
                chunks=chunks,
                relations=relations,
                acl=acl,
                media_assets=media_assets,
                symbols=symbols,
                sync_state=sync_state,
                tombstones=tombstones,
            )
            manifest = ManifestRecordBuilder.build(
                dataset_version=dataset_version,
                export_mode="full_snapshot",
                generated_at=generated_at,
                config_hash=config_hash,
                chunker_version=chunker_version,
                schemas_version=schemas_version,
                counts=counts,
                source_scopes=source_scopes,
            )
            validator.validate_record("Manifest", manifest)
            _write_manifest(staging_path / "manifest.json", manifest)
            _verify_machine_files(staging_path)
            return manifest
        except Exception:
            _remove_owned_staging_path(staging_path)
            raise


def _write_jsonl_files(
    *,
    staging_path: Path,
    validator: FoundationSchemaValidator,
    documents: Iterable[Mapping[str, object]],
    chunks: Iterable[Mapping[str, object]],
    relations: Iterable[Mapping[str, object]],
    acl: Iterable[Mapping[str, object]],
    media_assets: Iterable[Mapping[str, object]],
    symbols: Iterable[Mapping[str, object]],
    sync_state: Iterable[Mapping[str, object]],
    tombstones: Iterable[Mapping[str, object]],
) -> dict[str, int]:
    streams: dict[str, Iterable[Mapping[str, object]]] = {
        "documents": documents,
        "chunks": chunks,
        "relations": relations,
        "acl": acl,
        "media_assets": media_assets,
        "symbols": symbols,
        "sync_state": sync_state,
        "tombstones": tombstones,
    }

    counts: dict[str, int] = {}
    for file_name, count_key, schema_name in JSONL_FILE_SCHEMA_PAIRS:
        counts[count_key] = JsonlRecordWriter.write(
            path=staging_path / file_name,
            records=_validated_records(
                validator=validator,
                schema_name=schema_name,
                records=streams[count_key],
            ),
        )

    return counts


def _validated_records(
    *,
    validator: FoundationSchemaValidator,
    schema_name: str,
    records: Iterable[Mapping[str, object]],
) -> Iterator[dict[str, object]]:
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("Foundation record must be a mapping")

        plain_record = dict(record)
        validator.validate_record(schema_name, plain_record)
        yield plain_record


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            manifest,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        handle.write("\n")


def _verify_machine_files(staging_path: Path) -> None:
    entries = list(staging_path.iterdir())
    actual_names = {entry.name for entry in entries}
    all_regular_files = all(
        entry.is_file() and not entry.is_symlink()
        for entry in entries
    )

    if actual_names != EXPECTED_MACHINE_FILES or not all_regular_files:
        raise RuntimeError(
            "Staging directory is incomplete or contains unexpected entries: "
            f"{sorted(actual_names)}"
        )


def _remove_owned_staging_path(staging_path: Path) -> None:
    try:
        shutil.rmtree(staging_path)
    except OSError:
        pass
