from __future__ import annotations

import shutil
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from knowledgenexus.foundation.cli.verify_w5_snapshot_pair import main, verify_pair


ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "tests" / "fixtures" / "foundation" / "golden_full_snapshot"


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    first, second = tmp_path / "a", tmp_path / "b"
    shutil.copytree(GOLDEN, first)
    shutil.copytree(GOLDEN, second)
    return first, second


def test_strict_pair_verification_accepts_identical_full_snapshots(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)

    result = verify_pair(first, second)

    assert result["status"] == "complete"
    assert result["strict_readback"] is True
    assert result["cross_stream_closed"] is True
    assert result["version_trees_identical"] is True
    assert result["counts"]["documents"] > 0


def test_strict_pair_verification_rejects_identically_corrupt_streams(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)
    version = (first / "LATEST.txt").read_text(encoding="utf-8").strip()
    for root in (first, second):
        (root / version / "documents.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        verify_pair(first, second)


def test_strict_pair_verification_rejects_staging_residue(tmp_path: Path) -> None:
    first, second = _pair(tmp_path)
    (first / ".staging-incomplete").mkdir()

    with pytest.raises(ValueError):
        verify_pair(first, second)


def test_strict_pair_verification_rejects_wrong_version_file_set(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)
    version = (first / "LATEST.txt").read_text(encoding="utf-8").strip()
    (first / version / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError):
        verify_pair(first, second)


def test_strict_pair_verification_rejects_nonregular_version_entry(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)
    version = (first / "LATEST.txt").read_text(encoding="utf-8").strip()
    manifest = first / version / "manifest.json"
    manifest.unlink()
    manifest.mkdir()

    with pytest.raises(ValueError):
        verify_pair(first, second)


def test_strict_pair_verification_rejects_empty_full_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _pair(tmp_path)
    counts = MappingProxyType({
        "documents": 0, "chunks": 0, "relations": 0, "acl": 0,
        "media_assets": 0, "symbols": 0, "sync_state": 0, "tombstones": 0,
    })
    snapshot = SimpleNamespace(
        digest="a" * 64,
        manifest=MappingProxyType({"export_mode": "full_snapshot", "counts": counts}),
        streams=MappingProxyType({}),
    )
    monkeypatch.setattr(
        "knowledgenexus.foundation.cli.verify_w5_snapshot_pair.PublishedSnapshotReader.read",
        lambda _self, _version: snapshot,
    )

    with pytest.raises(ValueError):
        verify_pair(first, second)


@pytest.mark.parametrize(
    "counts",
    [
        {"documents": 2, "chunks": 1, "relations": 0, "acl": 2, "media_assets": 0, "symbols": 0, "sync_state": 2, "tombstones": 0},
        {"documents": 1, "chunks": 1, "relations": 0, "acl": 0, "media_assets": 0, "symbols": 0, "sync_state": 1, "tombstones": 0},
        {"documents": 1, "chunks": 1, "relations": 0, "acl": 1, "media_assets": 1, "symbols": 0, "sync_state": 1, "tombstones": 0},
        {"documents": 1, "chunks": 1, "relations": 0, "acl": 1, "media_assets": 0, "symbols": 1, "sync_state": 1, "tombstones": 0},
        {"documents": 1, "chunks": 1, "relations": 0, "acl": 1, "media_assets": 0, "symbols": 0, "sync_state": 1, "tombstones": 1},
    ],
)
def test_strict_pair_verification_rejects_invalid_count_relationships(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counts: dict[str, int]
) -> None:
    first, second = _pair(tmp_path)
    snapshot = SimpleNamespace(
        digest="a" * 64,
        manifest=MappingProxyType({
            "export_mode": "full_snapshot", "counts": MappingProxyType(counts)
        }),
        streams=MappingProxyType({}),
    )
    monkeypatch.setattr(
        "knowledgenexus.foundation.cli.verify_w5_snapshot_pair.PublishedSnapshotReader.read",
        lambda _self, _version: snapshot,
    )

    with pytest.raises(ValueError):
        verify_pair(first, second)


def test_cli_failure_is_sanitized(tmp_path: Path, capsys) -> None:
    first, second = _pair(tmp_path)
    (second / "LATEST.txt").write_text("invalid\n", encoding="utf-8")

    assert main(["--dataset-root-a", str(first), "--dataset-root-b", str(second)]) == 1
    assert capsys.readouterr().out == '{"status":"failed"}\n'
