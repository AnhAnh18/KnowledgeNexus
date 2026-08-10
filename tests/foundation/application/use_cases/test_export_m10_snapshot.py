from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import knowledgenexus.foundation.application.use_cases.export_m10_snapshot as export_m10
from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import ExportM10Snapshot, M10SnapshotExportFailure
from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import M10FullSnapshotExporter
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher import FullSnapshotPublisher
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import FullSnapshotStagingCompleter
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import FullSnapshotStagingWriter
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
from knowledgenexus.foundation.domain.models.m10_composition import (
    M10ConfluenceHandoff,
    M10GitHandoff,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10MediaPolicy
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class _Adapter:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def collect(self, request):
        self.calls += 1
        return self.value


def _custom_exporter(*, validator=None, publisher=None, confluence, git):
    return ExportM10Snapshot(
        confluence_adapter=_Adapter(confluence),
        git_adapter=_Adapter(git),
        schema_validator=validator,
        staging_writer=FullSnapshotStagingWriter,
        staging_completer=FullSnapshotStagingCompleter,
        publisher=publisher or FullSnapshotPublisher,
    )


class _ReportMutatingPublisher:
    @staticmethod
    def publish(**kwargs):
        final_path = FullSnapshotPublisher.publish(**kwargs)
        (final_path / "quality_report.md").write_bytes(b"tampered report")
        return final_path


class _TrackingPublisher:
    def __init__(self, validator):
        self.validator = validator

    def publish(self, **kwargs):
        final_path = FullSnapshotPublisher.publish(**kwargs)
        self.validator.final_path = final_path
        return final_path


def test_acceptance_failure_restores_pointer_and_removes_new_final(tmp_path):
    request = _request(tmp_path)
    previous = tmp_path / "v-previous"
    previous.mkdir()
    marker = previous / "keep.txt"
    marker.write_bytes(b"prior snapshot")
    prior_latest = b"v-previous\r\n"
    (tmp_path / "LATEST.txt").write_bytes(prior_latest)
    confluence, git = _handoffs()

    exporter = _custom_exporter(
        confluence=confluence,
        git=git,
        publisher=_ReportMutatingPublisher,
    )
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(request)

    assert exc.value.category == "acceptance"
    assert (tmp_path / "LATEST.txt").read_bytes() == prior_latest
    assert not (tmp_path / "v20260805-000000-000000Z").exists()
    assert marker.read_bytes() == b"prior snapshot"


def test_acceptance_rejects_validator_mutation_and_cleans_publication(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    validator = FoundationSchemaValidator()
    original_validate = validator.validate_record
    validator.final_path = None

    def mutating_validate(schema_name, record, *args, **kwargs):
        if validator.final_path is not None and schema_name == "Manifest":
            record["generated_at"] = "2026-08-05T00:00:01Z"
        return original_validate(schema_name, record, *args, **kwargs)

    validator.validate_record = mutating_validate
    exporter = _custom_exporter(
        confluence=confluence,
        git=git,
        validator=validator,
        publisher=_TrackingPublisher(validator),
    )
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(request)

    assert exc.value.category == "acceptance"
    assert not (tmp_path / "v20260805-000000-000000Z").exists()
    assert not (tmp_path / "LATEST.txt").exists()


def test_acceptance_rejects_validator_on_disk_tampering(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    validator = FoundationSchemaValidator()
    original_validate = validator.validate_record
    validator.final_path = None

    def tampering_validate(schema_name, record, *args, **kwargs):
        if validator.final_path is not None and schema_name == "Manifest":
            (validator.final_path / "manifest.json").write_bytes(b"{}")
        return original_validate(schema_name, record, *args, **kwargs)

    validator.validate_record = tampering_validate
    exporter = _custom_exporter(
        confluence=confluence,
        git=git,
        validator=validator,
        publisher=_TrackingPublisher(validator),
    )
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(request)

    assert exc.value.category == "acceptance"
    assert not (tmp_path / "v20260805-000000-000000Z").exists()
    assert not (tmp_path / "LATEST.txt").exists()


def test_digest_failure_is_sanitized_and_rolls_back(tmp_path, monkeypatch):
    request = _request(tmp_path)
    confluence, git = _handoffs()

    def explode(_path):
        raise RuntimeError("secret digest path")

    monkeypatch.setattr(export_m10, "_snapshot_digest", explode)
    exporter = _custom_exporter(confluence=confluence, git=git)
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(request)

    assert exc.value.category == "acceptance"
    assert not (tmp_path / "v20260805-000000-000000Z").exists()
    assert not (tmp_path / "LATEST.txt").exists()


def test_export_m10_publishes_using_m3_and_derives_counts(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    left, right = _Adapter(confluence), _Adapter(git)
    result = M10FullSnapshotExporter(confluence_adapter=left, git_adapter=right).execute(request)
    assert result.status == "published"
    assert result.dataset_version == "v20260805-000000-000000Z"
    assert result.metrics.documents == 2
    assert sorted(path.name for path in result.final_path.iterdir()) == sorted([
        "acl.jsonl", "chunks.jsonl", "documents.jsonl", "manifest.json", "media_assets.jsonl",
        "quality_report.md", "relations.jsonl", "symbols.jsonl", "sync_state.jsonl", "tombstones.jsonl",
    ])
    assert left.calls == right.calls == 1


@pytest.mark.parametrize("bad", [None, object(), {"request": True}])
def test_invalid_request_fails_before_adapter_calls(tmp_path, bad):
    confluence, git = _handoffs()
    left, right = _Adapter(confluence), _Adapter(git)
    exporter = M10FullSnapshotExporter(confluence_adapter=left, git_adapter=right)
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(bad)
    assert exc.value.category == "invalid_request"
    assert left.calls == right.calls == 0


def test_adapter_errors_are_sanitized(tmp_path):
    class Exploding:
        def collect(self, request):
            raise RuntimeError("secret path and page body")

    _, git = _handoffs()
    with pytest.raises(M10SnapshotExportFailure) as exc:
        M10FullSnapshotExporter(confluence_adapter=Exploding(), git_adapter=_Adapter(git)).execute(_request(tmp_path))
    assert exc.value.category == "adapter"
    assert "secret" not in str(exc.value)


def test_constructor_sanitizes_throwing_dependency_attributes():
    class Bad:
        @property
        def collect(self):
            raise RuntimeError("secret adapter detail")

    with pytest.raises(M10SnapshotExportFailure) as exc:
        M10FullSnapshotExporter(confluence_adapter=Bad(), git_adapter=object())
    assert exc.value.category == "adapter"
    assert "secret" not in str(exc.value)


def test_second_export_is_no_clobber(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    left, right = _Adapter(confluence), _Adapter(git)
    exporter = M10FullSnapshotExporter(confluence_adapter=left, git_adapter=right)
    exporter.execute(request)
    with pytest.raises(M10SnapshotExportFailure) as exc:
        exporter.execute(request)
    assert exc.value.category == "publication"
    assert left.calls == right.calls == 1
    assert (tmp_path / "LATEST.txt").read_text(encoding="utf-8") == "v20260805-000000-000000Z\n"
