from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from knowledgenexus.foundation.infrastructure.exporters import (
    FullSnapshotPublisher,
    FullSnapshotStagingCompleter,
    FullSnapshotStagingWriter,
)
from knowledgenexus.foundation.infrastructure.exporters import (
    full_snapshot_publisher as publisher_module,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import (
    EXPECTED_COMPLETE_FILES,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)
from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)


VALID_DATASET_VERSION = "v20260714-103015-123456Z"
OLD_DATASET_VERSION = "v20260713-000000-000001Z"
VALID_GENERATED_AT = "2026-07-14T10:30:15Z"
VALID_CONFIG_HASH = "a" * 64
VALID_CHUNKER_VERSION = "1.2.0"
VALID_SCHEMAS_VERSION = "1.0"


def test_successfully_publishes_completed_staging_and_updates_latest(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    before = _snapshot_bytes(staging_path)

    final_path = _publish(staging_path, dataset_root)

    assert final_path == dataset_root / VALID_DATASET_VERSION
    assert not staging_path.exists()
    assert final_path.is_dir()
    assert _entry_names(final_path) == EXPECTED_COMPLETE_FILES
    assert _snapshot_bytes(final_path) == before
    assert (dataset_root / "LATEST.txt").read_bytes() == (
        VALID_DATASET_VERSION + "\n"
    ).encode("utf-8")
    assert not _latest_temp_files(dataset_root)


def test_latest_serialization_is_exact_utf8_dataset_version_line(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")

    _publish(staging_path, dataset_root)

    latest_bytes = (dataset_root / "LATEST.txt").read_bytes()
    assert latest_bytes == b"v20260714-103015-123456Z\n"
    assert not latest_bytes.startswith(b"\xef\xbb\xbf")
    assert latest_bytes.count(b"\n") == 1
    assert b"/" not in latest_bytes
    assert b"\\" not in latest_bytes
    assert b'"' not in latest_bytes


def test_existing_regular_latest_is_replaced_and_old_entries_are_preserved(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    latest_path = dataset_root / "LATEST.txt"
    latest_path.write_text(OLD_DATASET_VERSION + "\n", encoding="utf-8")
    old_snapshot = dataset_root / OLD_DATASET_VERSION
    old_snapshot.mkdir()
    old_sentinel = old_snapshot / "sentinel.txt"
    old_sentinel.write_text("old snapshot", encoding="utf-8")
    unrelated = dataset_root / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    staging_path = _create_completed_staging(dataset_root / "staging")

    _publish(staging_path, dataset_root)

    assert latest_path.read_bytes() == (VALID_DATASET_VERSION + "\n").encode()
    assert old_sentinel.read_text(encoding="utf-8") == "old snapshot"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_missing_dataset_root_is_not_created_and_staging_is_not_moved(
    tmp_path: Path,
) -> None:
    staging_path = _create_completed_staging(tmp_path / "staging")
    dataset_root = tmp_path / "missing-dataset"

    with pytest.raises(FileNotFoundError):
        _publish(staging_path, dataset_root)

    assert not dataset_root.exists()
    assert staging_path.is_dir()


def test_non_directory_dataset_root_is_not_modified(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.write_text("sentinel", encoding="utf-8")
    staging_path = _create_completed_staging(tmp_path / "staging")

    with pytest.raises(NotADirectoryError):
        _publish(staging_path, dataset_root)

    assert dataset_root.read_text(encoding="utf-8") == "sentinel"
    assert staging_path.is_dir()


def test_missing_staging_path_does_not_change_latest(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    latest_path = _write_old_latest(dataset_root)

    with pytest.raises(FileNotFoundError):
        _publish(dataset_root / "missing", dataset_root)

    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"


def test_non_directory_staging_path_is_rejected(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = dataset_root / "staging"
    staging_path.write_text("sentinel", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        _publish(staging_path, dataset_root)

    assert staging_path.read_text(encoding="utf-8") == "sentinel"


def test_staging_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    real_staging = _create_completed_staging(dataset_root / "real-staging")
    staging_link = dataset_root / "staging"
    _create_symlink_or_skip(staging_link, real_staging, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        _publish(staging_link, dataset_root)

    assert staging_link.is_symlink()
    assert real_staging.is_dir()


@pytest.mark.parametrize("location", ["sibling", "nested", "other-root"])
def test_staging_must_be_a_direct_dataset_root_child(
    tmp_path: Path,
    location: str,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    latest_path = _write_old_latest(dataset_root)
    if location == "sibling":
        staging_path = _create_completed_staging(tmp_path / "staging")
    elif location == "nested":
        nested_parent = dataset_root / "nested"
        nested_parent.mkdir()
        staging_path = _create_completed_staging(nested_parent / "staging")
    else:
        other_root = tmp_path / "other-root"
        other_root.mkdir()
        staging_path = _create_completed_staging(other_root / "staging")

    with pytest.raises(ValueError, match="direct child"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"


def test_incomplete_staging_is_rejected_without_publication(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    (staging_path / "chunks.jsonl").unlink()
    latest_path = _write_old_latest(dataset_root)

    with pytest.raises(RuntimeError, match="incomplete"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert not (dataset_root / VALID_DATASET_VERSION).exists()
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_unexpected_staging_entry_is_rejected_and_preserved(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    unexpected = staging_path / "unexpected"
    if entry_kind == "file":
        unexpected.write_text("keep", encoding="utf-8")
    else:
        unexpected.mkdir()

    with pytest.raises(RuntimeError, match="unexpected"):
        _publish(staging_path, dataset_root)

    assert unexpected.exists()
    assert staging_path.is_dir()


def test_symlink_inside_staging_is_rejected_when_supported(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    documents_path = staging_path / "documents.jsonl"
    outside = tmp_path / "outside-documents.jsonl"
    outside.write_bytes(documents_path.read_bytes())
    documents_path.unlink()
    _create_symlink_or_skip(documents_path, outside)

    with pytest.raises(RuntimeError, match="incomplete"):
        _publish(staging_path, dataset_root)

    assert documents_path.is_symlink()
    assert staging_path.is_dir()


def test_invalid_manifest_json_propagates_without_publication(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    (staging_path / "manifest.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert not (dataset_root / VALID_DATASET_VERSION).exists()


def test_manifest_schema_validation_failure_propagates(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    _mutate_manifest(
        staging_path,
        lambda manifest: manifest.__setitem__("generated_at", "invalid"),
    )

    with pytest.raises(FoundationValidationError):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()


def test_delta_manifest_is_rejected_before_publication(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")

    def make_delta(manifest: dict[str, object]) -> None:
        manifest["export_mode"] = "delta"
        manifest["base_dataset_version"] = OLD_DATASET_VERSION

    _mutate_manifest(staging_path, make_delta)

    with pytest.raises(ValueError, match="export_mode"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()


def test_full_snapshot_with_base_version_is_rejected(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    _mutate_manifest(
        staging_path,
        lambda manifest: manifest.__setitem__(
            "base_dataset_version",
            OLD_DATASET_VERSION,
        ),
    )

    with pytest.raises(ValueError, match="base_dataset_version"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()


@pytest.mark.parametrize("case", ["missing", "extra"])
def test_wrong_count_key_set_is_rejected(tmp_path: Path, case: str) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")

    def change_counts(manifest: dict[str, object]) -> None:
        counts = manifest["counts"]
        assert isinstance(counts, dict)
        if case == "missing":
            del counts["chunks"]
        else:
            counts["unexpected"] = 0

    _mutate_manifest(staging_path, change_counts)

    with pytest.raises(ValueError, match="exactly"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()


@pytest.mark.parametrize(
    ("invalid_value", "expected_error"),
    [(True, TypeError), (-1, ValueError)],
)
def test_invalid_count_values_are_rejected_by_publisher_boundary(
    invalid_value: object,
    expected_error: type[Exception],
) -> None:
    manifest: dict[str, object] = {
        "export_mode": "full_snapshot",
        "dataset_version": VALID_DATASET_VERSION,
    }
    counts = {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 0,
    }
    counts["documents"] = invalid_value  # type: ignore[assignment]
    manifest["counts"] = counts

    with pytest.raises(expected_error):
        publisher_module._verify_publisher_invariants(manifest)


@pytest.mark.parametrize(
    "dataset_version",
    [
        "../escape",
        "version/child",
        "version\\child",
        ".",
        "..",
        "not-a-foundation-version",
    ],
)
def test_unsafe_dataset_version_is_rejected_before_path_derivation(
    tmp_path: Path,
    dataset_version: str,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    _mutate_manifest(
        staging_path,
        lambda manifest: manifest.__setitem__("dataset_version", dataset_version),
    )
    latest_path = _write_old_latest(dataset_root)
    root_entries_before = _entry_names(dataset_root)

    with pytest.raises(ValueError, match="dataset_version"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert _entry_names(dataset_root) == root_entries_before
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("entry_kind", ["directory", "file"])
def test_existing_final_entry_is_never_overwritten(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    final_path = dataset_root / VALID_DATASET_VERSION
    if entry_kind == "directory":
        final_path.mkdir()
        sentinel = final_path / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
    else:
        final_path.write_text("keep", encoding="utf-8")
    latest_path = _write_old_latest(dataset_root)

    with pytest.raises(FileExistsError):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    if entry_kind == "directory":
        assert sentinel.read_text(encoding="utf-8") == "keep"
    else:
        assert final_path.read_text(encoding="utf-8") == "keep"
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"


@pytest.mark.parametrize("dangling", [False, True])
def test_existing_final_symlink_is_never_overwritten(
    tmp_path: Path,
    dangling: bool,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    target = dataset_root / "target"
    if not dangling:
        target.mkdir()
    final_path = dataset_root / VALID_DATASET_VERSION
    _create_symlink_or_skip(final_path, target, target_is_directory=True)

    with pytest.raises(FileExistsError):
        _publish(staging_path, dataset_root)

    assert final_path.is_symlink()
    assert staging_path.is_dir()


def test_latest_directory_is_rejected_before_staging_rename(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    latest_path = dataset_root / "LATEST.txt"
    latest_path.mkdir()

    with pytest.raises(FileExistsError):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert latest_path.is_dir()
    assert not (dataset_root / VALID_DATASET_VERSION).exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_latest_symlink_is_rejected_before_staging_rename(
    tmp_path: Path,
    dangling: bool,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    target = dataset_root / "latest-target.txt"
    if not dangling:
        target.write_text(OLD_DATASET_VERSION + "\n", encoding="utf-8")
    latest_path = dataset_root / "LATEST.txt"
    _create_symlink_or_skip(latest_path, target)

    with pytest.raises(FileExistsError):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert latest_path.is_symlink()


def test_directory_rename_failure_leaves_staging_and_latest_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    latest_path = _write_old_latest(dataset_root)
    original_rename = Path.rename

    def fail_staging_rename(path: Path, target: Path) -> Path:
        if path == staging_path:
            raise OSError("forced directory rename failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_staging_rename)

    with pytest.raises(OSError, match="forced directory rename failure"):
        _publish(staging_path, dataset_root)

    assert staging_path.is_dir()
    assert not (dataset_root / VALID_DATASET_VERSION).exists()
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"
    assert not _latest_temp_files(dataset_root)


def test_latest_temp_creation_failure_keeps_unadvertised_final_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    latest_path = _write_old_latest(dataset_root)

    def fail_temp_creation(*args: object, **kwargs: object) -> object:
        raise OSError("forced latest temp failure")

    monkeypatch.setattr(
        publisher_module.tempfile,
        "NamedTemporaryFile",
        fail_temp_creation,
    )

    with pytest.raises(OSError, match="forced latest temp failure"):
        _publish(staging_path, dataset_root)

    final_path = dataset_root / VALID_DATASET_VERSION
    assert final_path.is_dir()
    assert not staging_path.exists()
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"
    assert not _latest_temp_files(dataset_root)


def test_latest_replace_failure_keeps_final_and_old_latest_without_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    staging_path = _create_completed_staging(dataset_root / "staging")
    latest_path = _write_old_latest(dataset_root)
    before = _snapshot_bytes(staging_path)
    original_replace = Path.replace

    def fail_latest_replace(path: Path, target: Path) -> Path:
        if target == latest_path:
            raise OSError("forced latest replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_latest_replace)

    with pytest.raises(OSError, match="forced latest replace failure"):
        _publish(staging_path, dataset_root)

    final_path = dataset_root / VALID_DATASET_VERSION
    assert final_path.is_dir()
    assert _snapshot_bytes(final_path) == before
    assert not staging_path.exists()
    assert latest_path.read_text(encoding="utf-8") == OLD_DATASET_VERSION + "\n"
    assert not _latest_temp_files(dataset_root)


def test_second_publication_for_same_version_fails_without_modification(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    first_staging = _create_completed_staging(dataset_root / "staging-one")
    final_path = _publish(first_staging, dataset_root)
    final_before = _snapshot_bytes(final_path)
    latest_before = (dataset_root / "LATEST.txt").read_bytes()
    second_staging = _create_completed_staging(dataset_root / "staging-two")

    with pytest.raises(FileExistsError):
        _publish(second_staging, dataset_root)

    assert _snapshot_bytes(final_path) == final_before
    assert second_staging.is_dir()
    assert (dataset_root / "LATEST.txt").read_bytes() == latest_before


def _create_completed_staging(
    staging_path: Path,
    *,
    dataset_version: str = VALID_DATASET_VERSION,
) -> Path:
    FullSnapshotStagingWriter.write(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
        dataset_version=dataset_version,
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        documents=[build_sample_document_record()],
        chunks=[build_sample_chunk_record()],
        relations=[build_sample_relation_record()],
        acl=[build_sample_acl_record()],
        media_assets=[],
        symbols=[],
        sync_state=[],
        tombstones=[],
    )
    FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=FoundationSchemaValidator(),
    )
    return staging_path


def _publish(staging_path: Path, dataset_root: Path) -> Path:
    return FullSnapshotPublisher.publish(
        staging_path=staging_path,
        dataset_root=dataset_root,
        validator=FoundationSchemaValidator(),
    )


def _read_manifest(staging_path: Path) -> dict[str, object]:
    manifest = json.loads(
        (staging_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(manifest, dict)
    return manifest


def _mutate_manifest(
    staging_path: Path,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    manifest = copy.deepcopy(_read_manifest(staging_path))
    mutation(manifest)
    serialized = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    (staging_path / "manifest.json").write_text(
        serialized + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_old_latest(dataset_root: Path) -> Path:
    latest_path = dataset_root / "LATEST.txt"
    latest_path.write_text(OLD_DATASET_VERSION + "\n", encoding="utf-8")
    return latest_path


def _snapshot_bytes(snapshot_path: Path) -> dict[str, bytes]:
    return {
        name: (snapshot_path / name).read_bytes()
        for name in EXPECTED_COMPLETE_FILES
    }


def _entry_names(path: Path) -> set[str]:
    return {entry.name for entry in path.iterdir()}


def _latest_temp_files(dataset_root: Path) -> list[Path]:
    return list(dataset_root.glob(".LATEST.txt.*.tmp"))


def _create_symlink_or_skip(
    link_path: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link_path.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
