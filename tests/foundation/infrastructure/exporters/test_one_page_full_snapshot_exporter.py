from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.one_page_export import (
    ONE_PAGE_DATASET_NAME,
)
from knowledgenexus.foundation.infrastructure.exporters.one_page_full_snapshot_exporter import (
    OnePageFullSnapshotExportError,
    OnePageFullSnapshotExporter,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from tests.fixtures.foundation.one_page_export_snapshot_fixtures import (
    build_one_page_export_projection,
)

VALID_GENERATED_AT = "2026-07-14T00:00:00Z"


def _dataset_root(export_root: Path) -> Path:
    root = export_root / ONE_PAGE_DATASET_NAME
    root.mkdir(parents=True)
    return root


def _export(export_root: Path, **overrides: object):
    fields: dict[str, object] = {
        "projection": build_one_page_export_projection(),
        "generated_at": VALID_GENERATED_AT,
        "export_root": export_root,
        "validator": FoundationSchemaValidator(),
    }
    fields.update(overrides)
    return OnePageFullSnapshotExporter.export(**fields)  # type: ignore[arg-type]


# --- A: configuration validation ---------------------------------------------


def test_success_exports_full_snapshot(tmp_path: Path) -> None:
    _dataset_root(tmp_path)

    result = _export(tmp_path)

    assert result.final_path.is_dir()
    assert result.acceptance.final_file_set_valid is True
    assert result.acceptance.latest_pointer_valid is True
    assert (tmp_path / ONE_PAGE_DATASET_NAME / "LATEST.txt").read_text(
        encoding="utf-8"
    ) == f"{result.dataset_version}\n"


def test_dataset_root_missing_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export(tmp_path)
    assert excinfo.value.category == "export_configuration"
    assert not (tmp_path / ONE_PAGE_DATASET_NAME).exists()


def test_dataset_root_as_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ONE_PAGE_DATASET_NAME).write_text("not a directory", encoding="utf-8")
    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export(tmp_path)
    assert excinfo.value.category == "export_configuration"


@pytest.mark.skipif(
    not hasattr(Path, "symlink_to"), reason="symlink support required"
)
def test_dataset_root_as_symlink_is_rejected(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / ONE_PAGE_DATASET_NAME
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export(tmp_path)
    assert excinfo.value.category == "export_configuration"


def test_export_root_wrong_type_is_rejected() -> None:
    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export("not-a-path")  # type: ignore[arg-type]
    assert excinfo.value.category == "export_configuration"


@pytest.mark.parametrize(
    "generated_at",
    [
        "2026-07-14T00:00:00",  # naive, no zone
        "not-a-timestamp",
        "2026-13-40T00:00:00Z",  # impossible calendar value
        "2026-07-14 00:00:00Z",  # missing T separator
    ],
)
def test_malformed_generated_at_is_rejected(tmp_path: Path, generated_at: str) -> None:
    _dataset_root(tmp_path)
    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export(tmp_path, generated_at=generated_at)
    assert excinfo.value.category == "export_configuration"
    assert not any((tmp_path / ONE_PAGE_DATASET_NAME).iterdir())


def test_equivalent_offsets_of_same_instant_produce_same_dataset_version(
    tmp_path: Path,
) -> None:
    _dataset_root(tmp_path / "a")
    _dataset_root(tmp_path / "b")

    result_z = _export(tmp_path / "a", generated_at="2026-07-14T00:00:00Z")
    result_offset = _export(
        tmp_path / "b", generated_at="2026-07-14T02:00:00+02:00"
    )

    assert result_z.dataset_version == result_offset.dataset_version


def test_fractional_seconds_generated_at_is_accepted(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    result = _export(tmp_path, generated_at="2026-07-14T00:00:00.123456Z")
    assert result.manifest["generated_at"] == "2026-07-14T00:00:00.123456Z"


def test_no_directory_is_auto_created_on_configuration_failure(tmp_path: Path) -> None:
    with pytest.raises(OnePageFullSnapshotExportError):
        _export(tmp_path)
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


# --- B/C: staging + manifest-count closure -----------------------------------


def test_entry_snapshot_still_equals_projection_after_success(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    projection = build_one_page_export_projection()
    before = deepcopy(projection)

    _export(tmp_path, projection=projection)

    assert projection == before


def test_pre_existing_staging_path_fails_closed_as_export_staging(
    tmp_path: Path,
) -> None:
    from knowledgenexus.foundation.domain.rules.dataset_version_generator import (
        DatasetVersionGenerator,
    )
    from datetime import datetime, timezone

    dataset_root = _dataset_root(tmp_path)
    dataset_version = DatasetVersionGenerator.generate(
        instant=datetime(2026, 7, 14, tzinfo=timezone.utc)
    )
    (dataset_root / f".staging-{dataset_version}").mkdir()

    with pytest.raises(OnePageFullSnapshotExportError) as excinfo:
        _export(tmp_path, generated_at="2026-07-14T00:00:00Z")
    assert excinfo.value.category == "export_staging"


def test_writer_streams_are_deep_copies_not_caller_tuples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledgenexus.foundation.infrastructure.exporters import (
        one_page_full_snapshot_exporter as exporter_module,
    )

    _dataset_root(tmp_path)
    projection = build_one_page_export_projection()
    captured: dict[str, object] = {}
    original_write = exporter_module.FullSnapshotStagingWriter.write

    def capture_and_write(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return original_write(**kwargs)

    monkeypatch.setattr(
        exporter_module.FullSnapshotStagingWriter, "write", staticmethod(capture_and_write)
    )

    _export(tmp_path, projection=projection)

    for stream_name in ("documents", "chunks", "relations", "acl"):
        writer_stream = captured[stream_name]
        projection_stream = getattr(projection, stream_name)
        assert writer_stream is not projection_stream
        for writer_record, projection_record in zip(writer_stream, projection_stream):
            assert writer_record is not projection_record
            assert writer_record == projection_record


def test_final_path_has_exactly_ten_expected_files(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    result = _export(tmp_path)

    names = {entry.name for entry in result.final_path.iterdir()}
    assert names == {
        "documents.jsonl",
        "chunks.jsonl",
        "relations.jsonl",
        "acl.jsonl",
        "media_assets.jsonl",
        "symbols.jsonl",
        "sync_state.jsonl",
        "tombstones.jsonl",
        "manifest.json",
        "quality_report.md",
    }
    assert len(names) == 10


# --- G: post-publication acceptance ------------------------------------------


def test_deferred_streams_are_zero_byte(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    result = _export(tmp_path)

    for name in ("media_assets.jsonl", "symbols.jsonl", "sync_state.jsonl", "tombstones.jsonl"):
        assert (result.final_path / name).stat().st_size == 0


def test_manifest_counts_match_expected(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    result = _export(tmp_path)

    assert result.manifest["counts"] == {
        "documents": 1,
        "chunks": 1,
        "relations": 1,
        "acl": 1,
        "media_assets": 0,
        "symbols": 0,
        "sync_state": 0,
        "tombstones": 0,
    }
    assert result.acceptance.manifest_counts_match is True


def test_quality_report_contains_pending_publication_state(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    result = _export(tmp_path)

    report = (result.final_path / "quality_report.md").read_text(encoding="utf-8")
    assert report.count("PENDING_AT_REPORT_COMPLETION") == 3
    assert result.acceptance.quality_report_unchanged_after_publication is True


def test_records_match_projection_source(tmp_path: Path) -> None:
    _dataset_root(tmp_path)
    projection = build_one_page_export_projection()

    result = _export(tmp_path, projection=projection)

    published_document = json.loads(
        (result.final_path / "documents.jsonl").read_text(encoding="utf-8").strip()
    )
    assert published_document == dict(projection.documents[0])
    assert result.acceptance.records_match_projection is True


# --- I.iii: exporter-level deterministic repeat ------------------------------


def test_exporter_level_deterministic_repeat_across_independent_roots(
    tmp_path: Path,
) -> None:
    projection = build_one_page_export_projection()
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    _dataset_root(root_a)
    _dataset_root(root_b)

    result_a = _export(root_a, projection=deepcopy(projection))
    result_b = _export(root_b, projection=deepcopy(projection))

    assert result_a.dataset_version == result_b.dataset_version

    def _tree_bytes(base: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(base)): path.read_bytes()
            for path in sorted(base.rglob("*"))
            if path.is_file()
        }

    tree_a = _tree_bytes(root_a / ONE_PAGE_DATASET_NAME)
    tree_b = _tree_bytes(root_b / ONE_PAGE_DATASET_NAME)
    assert tree_a == tree_b
