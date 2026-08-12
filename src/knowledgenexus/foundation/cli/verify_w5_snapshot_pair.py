"""Read-only strict verification of the two W5 full-snapshot publications."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from knowledgenexus.foundation.infrastructure.exporters.delta_snapshot_reader import (
    PublishedSnapshotReader,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_VERSION = re.compile(r"^v[0-9]{8}-[0-9]{6}-[0-9]{6}Z$")
_COUNT_KEYS = (
    "documents",
    "chunks",
    "relations",
    "acl",
    "media_assets",
    "symbols",
    "sync_state",
    "tombstones",
)
_VERSION_FILES = {
    "acl.jsonl",
    "chunks.jsonl",
    "documents.jsonl",
    "manifest.json",
    "media_assets.jsonl",
    "quality_report.md",
    "relations.jsonl",
    "symbols.jsonl",
    "sync_state.jsonl",
    "tombstones.jsonl",
}


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if callable(is_junction) and is_junction(path):
        return True
    return bool(
        getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0)
        & 0x400
    )


def _plain_root(value: str) -> Path:
    path = Path(value)
    if type(path) is not type(Path()) or not path.is_absolute() or not path.is_dir():
        raise ValueError("snapshot root is invalid")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if _is_reparse(current):
            raise ValueError("snapshot root is invalid")
    return path


def _latest(root: Path) -> str:
    latest = root / "LATEST.txt"
    if not latest.is_file() or _is_reparse(latest):
        raise ValueError("LATEST is invalid")
    payload = latest.read_bytes()
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("LATEST is invalid") from None
    if payload != f"{value.rstrip(chr(10))}\n".encode("utf-8"):
        raise ValueError("LATEST is invalid")
    version = value.removesuffix("\n")
    if _VERSION.fullmatch(version) is None:
        raise ValueError("LATEST is invalid")
    return version


def _require_complete_publication(root: Path, version: str) -> None:
    observed_root = {item.name for item in root.iterdir()}
    if observed_root != {"LATEST.txt", version}:
        raise ValueError("snapshot publication is incomplete")
    version_root = root / version
    if not version_root.is_dir() or _is_reparse(version_root):
        raise ValueError("snapshot publication is incomplete")
    entries = tuple(version_root.iterdir())
    if {item.name for item in entries} != _VERSION_FILES or any(
        not item.is_file() or _is_reparse(item) for item in entries
    ):
        raise ValueError("snapshot publication is incomplete")


def verify_pair(root_a: Path, root_b: Path) -> dict[str, object]:
    if type(root_a) is not type(Path()) or type(root_b) is not type(Path()):
        raise ValueError("snapshot roots are invalid")
    root_a, root_b = _plain_root(str(root_a)), _plain_root(str(root_b))
    if root_a == root_b:
        raise ValueError("snapshot roots must be distinct")
    version_a, version_b = _latest(root_a), _latest(root_b)
    if version_a != version_b:
        raise ValueError("snapshot versions differ")
    _require_complete_publication(root_a, version_a)
    _require_complete_publication(root_b, version_b)
    validator = FoundationSchemaValidator()
    first = PublishedSnapshotReader(dataset_root=root_a, validator=validator).read(
        version_a
    )
    second = PublishedSnapshotReader(dataset_root=root_b, validator=validator).read(
        version_b
    )
    if (
        first.digest != second.digest
        or first.manifest != second.manifest
        or first.streams != second.streams
        or first.manifest.get("export_mode") != "full_snapshot"
    ):
        raise ValueError("snapshot publications differ")
    counts = first.manifest.get("counts")
    if (
        not isinstance(counts, Mapping)
        or set(counts) != set(_COUNT_KEYS)
        or any(type(counts[key]) is not int or counts[key] < 0 for key in _COUNT_KEYS)
        or counts["documents"] <= 0
        or counts["chunks"] < counts["documents"]
        or counts["acl"] != counts["documents"]
        or counts["sync_state"] != counts["documents"] + counts["media_assets"]
        or counts["symbols"] != 0
        or counts["tombstones"] != 0
    ):
        raise ValueError("snapshot counts are invalid")
    return {
        "status": "complete",
        "strict_readback": True,
        "cross_stream_closed": True,
        "version_trees_identical": True,
        "counts": {key: counts[key] for key in _COUNT_KEYS},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root-a", required=True)
    parser.add_argument("--dataset-root-b", required=True)
    try:
        args = parser.parse_args(argv)
        payload = verify_pair(
            _plain_root(args.dataset_root_a), _plain_root(args.dataset_root_b)
        )
    except SystemExit as exc:
        return int(exc.code)
    except Exception:
        sys.stdout.write('{"status":"failed"}\n')
        return 1
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
