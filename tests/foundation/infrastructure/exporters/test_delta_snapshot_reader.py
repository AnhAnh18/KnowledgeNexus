from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from knowledgenexus.foundation.infrastructure.exporters.delta_snapshot_reader import (
    PublishedSnapshotReader,
    read_published_snapshot,
)
from knowledgenexus.foundation.infrastructure.exporters import delta_snapshot_reader as reader_module
from knowledgenexus.foundation.domain.rules.snapshot_readback import validate_snapshot_streams
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


_VERSION = "v20260714-000000-000000Z"


def _fixture() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "foundation" / "golden_full_snapshot" / _VERSION


def test_published_reader_validates_and_freezes_full_snapshot() -> None:
    root = _fixture().parents[0]
    reader = PublishedSnapshotReader(
        dataset_root=root,
        validator=FoundationSchemaValidator(),
    )

    result = reader.read(_VERSION)

    assert result.manifest["export_mode"] == "full_snapshot"
    assert len(result.streams["documents"]) == 1
    assert validate_snapshot_streams(result.streams, export_mode="full_snapshot").acl_closed
    with pytest.raises(TypeError):
        result.streams["documents"][0]["document_id"] = "changed"  # type: ignore[index]


def test_published_reader_rejects_invalid_version_and_snapshot_path() -> None:
    root = _fixture().parents[0]
    reader = PublishedSnapshotReader(
        dataset_root=root,
        validator=FoundationSchemaValidator(),
    )
    with pytest.raises(ValueError):
        reader.read("../secret")
    with pytest.raises(ValueError):
        read_published_snapshot(root, validator=FoundationSchemaValidator())
    with pytest.raises(ValueError, match="path/version mismatch"):
        read_published_snapshot(
            _fixture(),
            validator=FoundationSchemaValidator(),
            expected_dataset_version="v20260715-000000-000000Z",
        )


def test_published_reader_rejects_non_utf8_quality_report(tmp_path: Path) -> None:
    snapshot = tmp_path / _VERSION
    shutil.copytree(_fixture(), snapshot)
    (snapshot / "quality_report.md").write_bytes(b"\xff")

    with pytest.raises(ValueError, match="quality report"):
        read_published_snapshot(snapshot, validator=FoundationSchemaValidator())


def test_published_reader_rejects_windows_junction_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = getattr(reader_module.os.path, "isjunction", None)

    def isjunction(path: object) -> bool:
        if Path(path) == tmp_path:
            return True
        return bool(original(path)) if callable(original) else False

    monkeypatch.setattr(reader_module.os.path, "isjunction", isjunction, raising=False)

    with pytest.raises(ValueError, match="invalid dataset root"):
        PublishedSnapshotReader(
            dataset_root=tmp_path,
            validator=FoundationSchemaValidator(),
        )
