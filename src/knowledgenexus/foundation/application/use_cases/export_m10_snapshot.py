"""Generic, offline M10 full-snapshot application boundary.

The use case deliberately owns no connector, checkpoint, or credential state.
It composes two injected handoffs and then delegates filesystem work to the
authoritative M3 writer, completer, and publisher seams.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.compose_m10_snapshot import (
    ComposeM10Snapshot,
    M10CompositionFailure,
)
from knowledgenexus.foundation.application.use_cases.project_m10_delta import (
    M10DeltaOrchestrationResult,
)
from knowledgenexus.foundation.domain.models.delta_propagation import DeltaInventoryEntry
from knowledgenexus.foundation.domain.models.m10_snapshot import (
    M10QualityReportInput,
    M10SnapshotProjection,
    M10SnapshotRequest,
    M10SnapshotResult,
)
from knowledgenexus.foundation.domain.rules.dataset_version_generator import (
    DatasetVersionGenerator,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from knowledgenexus.foundation.ports.m10_snapshot_export_port import (
    M10PublisherPort,
    M10StagingCompleterPort,
    M10StagingWriterPort,
)
from knowledgenexus.foundation.domain.rules.snapshot_readback import (
    validate_snapshot_streams,
)


_JSONL_FILE_SCHEMA_PAIRS = (
    ("documents.jsonl", "documents", "CanonicalDocument"),
    ("chunks.jsonl", "chunks", "ChunkRecord"),
    ("relations.jsonl", "relations", "RelationRecord"),
    ("acl.jsonl", "acl", "ACLRecord"),
    ("media_assets.jsonl", "media_assets", "MediaAsset"),
    ("symbols.jsonl", "symbols", "SymbolRecord"),
    ("sync_state.jsonl", "sync_state", "SyncStateRecord"),
    ("tombstones.jsonl", "tombstones", "TombstoneRecord"),
)
_COUNT_KEYS = tuple(key for _, key, _ in _JSONL_FILE_SCHEMA_PAIRS)
_PUBLISHED_NAMES = frozenset({name for name, _, _ in _JSONL_FILE_SCHEMA_PAIRS} | {"manifest.json", "quality_report.md"})
_LATEST_FILE_NAME = "LATEST.txt"
_CONCRETE_PATH_TYPE = type(Path())


class M10SnapshotExportFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    ADAPTER = "adapter"
    PROJECTION = "projection"
    STAGING = "staging"
    COMPLETION = "completion"
    PUBLICATION = "publication"
    ACCEPTANCE = "acceptance"


class M10SnapshotExportFailure(Exception):
    """Sanitized application failure; only a closed category is exposed."""

    _CATEGORIES = frozenset(item.value for item in M10SnapshotExportFailureCategory)

    def __init__(self, category: str | M10SnapshotExportFailureCategory):
        if isinstance(category, M10SnapshotExportFailureCategory):
            category = category.value
        if type(category) is not str or category not in self._CATEGORIES:
            raise TypeError("invalid M10 failure category")
        self.category = M10SnapshotExportFailureCategory(category)
        super().__init__(self.category.value)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _strict_object(path: Path) -> dict[str, object]:
    return _strict_object_bytes(path.read_bytes())


def _strict_object_bytes(raw: bytes) -> dict[str, object]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    if type(value) is not dict:
        raise TypeError("JSON object expected")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite JSON constant")


def _strict_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    return _strict_jsonl_bytes(path.read_bytes())


def _strict_jsonl_bytes(raw: bytes) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for line in raw.decode("utf-8").splitlines():
        if not line:
            raise ValueError("blank JSONL line")
        value = json.loads(line, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        if type(value) is not dict:
            raise TypeError("JSONL object expected")
        records.append(value)
    return tuple(records)


def _validated_request(request: object) -> M10SnapshotRequest:
    # Read dataclass storage directly so a forged path-like object cannot run
    # filesystem methods before the exact runtime type check completes.
    if type(request) is not M10SnapshotRequest:
        raise M10SnapshotExportFailure("invalid_request")
    try:
        fields = vars(request)
        if set(fields) != set(M10SnapshotRequest.__dataclass_fields__):
            raise ValueError
        if type(fields["dataset_root"]) is not _CONCRETE_PATH_TYPE:
            raise ValueError
        M10SnapshotRequest.__post_init__(request)
    except Exception:
        raise M10SnapshotExportFailure("invalid_request") from None
    return request


def _derive_quality(request: M10SnapshotRequest, projection: M10SnapshotProjection) -> M10QualityReportInput:
    streams = {name: tuple(deepcopy(dict(row)) for row in getattr(projection, name)) for name in _COUNT_KEYS}
    expected_counts = {name: len(streams[name]) for name in _COUNT_KEYS}
    if expected_counts != {name: getattr(projection.metrics, name) for name in _COUNT_KEYS}:
        raise ValueError("projection metric count drift")
    relations = streams["relations"]
    jira = {
        "relations_total": len(relations),
        "resolved": sum(row.get("resolution_status") == "resolved" for row in relations),
        "unresolved": sum(row.get("resolution_status") != "resolved" for row in relations),
        "unresolved_without_jira_api": sum(row.get("resolution_status") == "unresolved_without_jira_api" for row in relations),
        "deferred_mvp": sum(row.get("resolution_status") == "deferred_mvp" for row in relations),
        "unresolved_target": sum(row.get("resolution_status") == "unresolved_target" for row in relations),
    }
    acl = {
        "documents_total": len(streams["documents"]),
        "documents_with_acl": len(streams["acl"]),
        "restricted_documents": sum(row.get("is_restricted") is True for row in streams["acl"]),
        "default_deny_chunks": sum(row.get("acl_tags") == ["restricted:unresolved"] for row in streams["chunks"]),
    }
    media = {
        "assets_total": len(streams["media_assets"]),
        "processed": sum(row.get("processing_status") in {"parsed", "ocr", "summarized"} for row in streams["media_assets"]),
        "failed": sum(row.get("processing_status") == "failed" for row in streams["media_assets"]),
        "not_processed": sum(row.get("processing_status") == "not_processed" for row in streams["media_assets"]),
    }
    symbols = {"symbols_total": len(streams["symbols"]), "resolved": sum(row.get("chunk_id") is not None for row in streams["symbols"])}
    sync = {
        "rows_total": len(streams["sync_state"]),
        "active": sum(row.get("status") == "active" for row in streams["sync_state"]),
        "pages": sum(row.get("entity_type") == "page" for row in streams["sync_state"]),
        "attachments": sum(row.get("entity_type") == "attachment" for row in streams["sync_state"]),
        "files": sum(row.get("entity_type") == "file" for row in streams["sync_state"]),
        "repos": sum(row.get("entity_type") == "repo" for row in streams["sync_state"]),
    }
    tombstones = {"rows_total": len(streams["tombstones"]), "initial_empty": int(not streams["tombstones"])}
    if request.export_mode == "full_snapshot" and tombstones["rows_total"] != 0:
        raise ValueError("initial tombstones must be empty")
    quality = M10QualityReportInput(
        active_profile=request.profile_bundle.chunking_profile.active_profile,
        profile_status=request.profile_bundle.chunking_profile.profile_status,
        chunker_version=projection.chunker_version,
        expected_counts=expected_counts,
        source_scopes=deepcopy(projection.source_scopes),
        jira_metrics=jira,
        acl_metrics=acl,
        media_metrics=media,
        symbol_metrics=symbols,
        sync_metrics=sync,
        tombstone_metrics=tombstones,
        completion_checks={"schema_validation": True, "counts_match": True, "tombstones_empty": not bool(streams["tombstones"]), "projection_consistency": True},
    )
    if projection.config_hash != request.profile_bundle.config_hash or projection.chunker_version != request.profile_bundle.chunking_profile.chunker_version:
        raise ValueError("profile or chunker drift")
    return quality


def _cleanup_staging(path: Path) -> None:
    try:
        if type(path) is _CONCRETE_PATH_TYPE and path.name.startswith(".staging-") and path.parent.is_dir() and not path.is_symlink() and path.is_dir():
            shutil.rmtree(path)
    except OSError:
        pass


def _snapshot_digest(final_path: Path) -> str:
    digest = hashlib.sha256()
    for name in sorted(_PUBLISHED_NAMES):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((final_path / name).read_bytes())
    return digest.hexdigest()


def _restore_latest_pointer(
    *,
    latest_path: Path,
    prior_exists: bool,
    prior_bytes: bytes | None,
    dataset_version: str,
) -> None:
    """Restore only the pointer state observed immediately before publication."""
    try:
        if prior_exists:
            if prior_bytes is None:
                return
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "wb",
                    dir=latest_path.parent,
                    prefix=f".{latest_path.name}.",
                    suffix=".rollback.tmp",
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    handle.write(prior_bytes)
                temp_path.replace(latest_path)
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            return

        # Do not remove an unrelated pointer created by another actor.
        if latest_path.is_symlink() or not latest_path.is_file():
            return
        if latest_path.read_bytes() == f"{dataset_version}\n".encode("utf-8"):
            latest_path.unlink()
    except Exception:
        pass


def _rollback_publication(
    *,
    root: Path,
    final_candidate: Path,
    final_preexisting: bool,
    latest_preexisting: bool,
    latest_bytes: bytes | None,
    dataset_version: str,
) -> None:
    """Best-effort cleanup of only this run's post-publication artifacts."""
    _restore_latest_pointer(
        latest_path=root / _LATEST_FILE_NAME,
        prior_exists=latest_preexisting,
        prior_bytes=latest_bytes,
        dataset_version=dataset_version,
    )
    if final_preexisting:
        return
    try:
        if (
            type(final_candidate) is _CONCRETE_PATH_TYPE
            and final_candidate.parent == root
            and final_candidate.name == dataset_version
            and final_candidate.is_dir()
            and not final_candidate.is_symlink()
        ):
            shutil.rmtree(final_candidate)
    except Exception:
        pass


def _sensitive_values(records: Mapping[str, tuple[dict[str, object], ...]], projection: M10SnapshotProjection, request: M10SnapshotRequest) -> set[str]:
    values: set[str] = {request.profile_bundle.config_hash}
    for stream in records.values():
        for record in stream:
            for key, value in record.items():
                if not isinstance(value, str):
                    continue
                lowered = key.lower()
                if any(token in lowered for token in ("id", "url", "path", "uri", "hash", "principal", "repo", "branch", "commit")) or value.startswith(("http://", "https://", "raw://")):
                    values.add(value)
    return {value for value in values if len(value) >= 8}


def _accept(final_path: Path, request: M10SnapshotRequest, projection: M10SnapshotProjection, dataset_version: str, generated_at: str, expected_counts: dict[str, int], quality_report: bytes, validator: FoundationSchemaValidator, *, prior_streams: Mapping[str, Sequence[Mapping[str, object]]] | None = None) -> None:
    root = request.dataset_root
    if final_path != root / dataset_version or type(final_path) is not _CONCRETE_PATH_TYPE or final_path.is_symlink() or not final_path.is_dir():
        raise ValueError
    entries = list(final_path.iterdir())
    if {entry.name for entry in entries} != _PUBLISHED_NAMES or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError
    validation_paths = {
        "manifest.json": final_path / "manifest.json",
        **{file_name: final_path / file_name for file_name, _, _ in _JSONL_FILE_SCHEMA_PAIRS},
    }
    validation_bytes = {name: path.read_bytes() for name, path in validation_paths.items()}

    def assert_validation_bytes_unchanged() -> None:
        for name, path in validation_paths.items():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != validation_bytes[name]:
                raise ValueError("validator mutated published bytes")

    manifest = _strict_object_bytes(validation_bytes["manifest.json"])
    isolated_manifest = deepcopy(manifest)
    validator.validate_record("Manifest", isolated_manifest)
    if isolated_manifest != manifest:
        raise ValueError("validator mutated manifest")
    assert_validation_bytes_unchanged()
    if manifest.get("dataset_version") != dataset_version or manifest.get("generated_at") != generated_at or manifest.get("export_mode") != request.export_mode or (request.export_mode == "delta" and manifest.get("base_dataset_version") != request.base_dataset_version) or manifest.get("config_hash") != projection.config_hash or manifest.get("chunker_version") != projection.chunker_version or manifest.get("schemas_version") != projection.schemas_version or _canonical_json(manifest.get("source_scopes")) != _canonical_json(projection.source_scopes) or _canonical_json(manifest.get("counts")) != _canonical_json(expected_counts):
        raise ValueError
    streams = {
        name: _strict_jsonl_bytes(validation_bytes[f"{name}.jsonl"])
        for name in _COUNT_KEYS
    }
    for file_name, name, schema in _JSONL_FILE_SCHEMA_PAIRS:
        for row in streams[name]:
            isolated_row = deepcopy(row)
            validator.validate_record(schema, isolated_row)
            if isolated_row != row:
                raise ValueError("validator mutated record")
            assert_validation_bytes_unchanged()
    validate_snapshot_streams(streams, export_mode=request.export_mode, prior_streams=prior_streams)
    if request.export_mode == "full_snapshot" and streams["tombstones"]:
        raise ValueError
    if request.export_mode == "delta":
        if any(row.get("dataset_version") != dataset_version for row in streams["tombstones"]):
            raise ValueError("tombstone dataset version does not match manifest")
    expected_streams = {name: tuple(getattr(projection, name)) for name in _COUNT_KEYS}
    if any(_canonical_json(list(streams[name])) != _canonical_json(list(expected_streams[name])) for name in _COUNT_KEYS):
        raise ValueError
    if (final_path / "quality_report.md").read_bytes() != quality_report:
        raise ValueError
    report = quality_report.decode("utf-8")
    if any(secret in report for secret in _sensitive_values(streams, projection, request)):
        raise ValueError
    latest = root / _LATEST_FILE_NAME
    if latest.is_symlink() or not latest.is_file() or latest.read_bytes() != f"{dataset_version}\n".encode("utf-8"):
        raise ValueError


class ExportM10Snapshot:
    """Compose and publish one validated M10 full snapshot."""

    def __init__(self, *, confluence_adapter: object, git_adapter: object, schema_validator: FoundationSchemaValidator | None = None, canonical_schema_validator: FoundationSchemaValidator | None = None, staging_writer: M10StagingWriterPort | None = None, staging_completer: M10StagingCompleterPort | None = None, publisher: M10PublisherPort | None = None, delta_orchestrator: object | None = None, delta_inventory: tuple[DeltaInventoryEntry, ...] = ()) -> None:
        try:
            if not callable(getattr(confluence_adapter, "collect", None)) or not callable(getattr(git_adapter, "collect", None)):
                raise TypeError
            if schema_validator is None:
                schema_validator = FoundationSchemaValidator()
            if type(schema_validator) is not FoundationSchemaValidator:
                raise TypeError
            if canonical_schema_validator is not None and type(canonical_schema_validator) is not FoundationSchemaValidator:
                raise TypeError
            if not callable(getattr(staging_writer, "write", None)) or not callable(getattr(staging_completer, "complete", None)) or not callable(getattr(publisher, "publish", None)):
                raise TypeError
            if delta_orchestrator is not None and not callable(getattr(delta_orchestrator, "execute", None)):
                raise TypeError
            if type(delta_inventory) is not tuple or any(type(item) is not DeltaInventoryEntry for item in delta_inventory):
                raise TypeError
        except Exception:
            raise M10SnapshotExportFailure("adapter") from None
        self._composer = ComposeM10Snapshot(confluence_adapter=confluence_adapter, git_adapter=git_adapter, schema_validator=schema_validator, canonical_schema_validator=canonical_schema_validator)
        self._validator = schema_validator
        self._staging_writer = staging_writer
        self._staging_completer = staging_completer
        self._publisher = publisher
        self._delta_orchestrator = delta_orchestrator
        self._delta_inventory = delta_inventory

    def execute(self, request: object, *, export_root: object | None = None, generated_at: object | None = None) -> M10SnapshotResult:
        request = _validated_request(request)
        if request.export_mode == "delta":
            if self._delta_orchestrator is None or not self._delta_inventory:
                raise M10SnapshotExportFailure("invalid_request")
        if export_root is not None and (type(export_root) is not _CONCRETE_PATH_TYPE or export_root != request.dataset_root):
            raise M10SnapshotExportFailure("invalid_request")
        if generated_at is not None and (type(generated_at) is not str or generated_at != request.generated_at):
            raise M10SnapshotExportFailure("invalid_request")
        try:
            parsed = datetime.fromisoformat(request.generated_at.replace("Z", "+00:00"))
            dataset_version = DatasetVersionGenerator.generate(instant=parsed)
        except Exception:
            raise M10SnapshotExportFailure("projection") from None
        staging_path = request.dataset_root / f".staging-{dataset_version}"
        final_candidate = request.dataset_root / dataset_version
        if staging_path.exists() or staging_path.is_symlink():
            raise M10SnapshotExportFailure("staging")
        if final_candidate.exists() or final_candidate.is_symlink():
            raise M10SnapshotExportFailure("publication")
        try:
            composed = self._composer.execute(request)
            projection = composed.projection
            if type(projection) is not M10SnapshotProjection:
                raise ValueError
            if request.export_mode == "delta" and self._delta_orchestrator is not None:
                orchestrated = self._delta_orchestrator.execute(
                    request,
                    projection,
                    inventory=self._delta_inventory,
                )
                if type(orchestrated) is not M10DeltaOrchestrationResult:
                    raise ValueError
                projection = orchestrated.projection
                delta_base_streams = orchestrated.base_streams
            else:
                delta_base_streams = None
            projection_before = deepcopy(projection)
            quality = _derive_quality(request, projection)
            generated_at = request.generated_at
        except M10CompositionFailure as exc:
            raise M10SnapshotExportFailure(exc.category.value) from None
        except Exception:
            raise M10SnapshotExportFailure("projection") from None

        try:
            manifest = self._staging_writer.write(staging_path=staging_path, validator=self._validator, dataset_version=dataset_version, generated_at=generated_at, config_hash=projection.config_hash, chunker_version=projection.chunker_version, schemas_version=projection.schemas_version, documents=projection.documents, chunks=projection.chunks, relations=projection.relations, acl=projection.acl, media_assets=projection.media_assets, symbols=projection.symbols, sync_state=projection.sync_state, tombstones=projection.tombstones, source_scopes=projection.source_scopes, export_mode=request.export_mode, base_dataset_version=request.base_dataset_version)
        except Exception:
            _cleanup_staging(staging_path)
            raise M10SnapshotExportFailure("staging") from None
        try:
            completed_manifest = self._staging_completer.complete(staging_path=staging_path, validator=self._validator, m10_quality=quality)
            if _canonical_json(completed_manifest) != _canonical_json(manifest):
                raise ValueError
            report_snapshot = (staging_path / "quality_report.md").read_bytes()
        except Exception:
            _cleanup_staging(staging_path)
            raise M10SnapshotExportFailure("completion") from None
        latest_path = request.dataset_root / _LATEST_FILE_NAME
        try:
            latest_preexisting = latest_path.exists() or latest_path.is_symlink()
            latest_bytes = (
                latest_path.read_bytes()
                if latest_preexisting and latest_path.is_file() and not latest_path.is_symlink()
                else None
            )
            final_preexisting = final_candidate.exists() or final_candidate.is_symlink()
            final_path = self._publisher.publish(staging_path=staging_path, dataset_root=request.dataset_root, validator=self._validator)
        except Exception:
            _cleanup_staging(staging_path)
            raise M10SnapshotExportFailure("publication") from None
        try:
            _accept(final_path, request, projection, dataset_version, generated_at, quality.expected_counts, report_snapshot, self._validator, prior_streams=delta_base_streams)
            if projection != projection_before:
                raise ValueError
            digest = _snapshot_digest(final_path)
        except Exception:
            _rollback_publication(
                root=request.dataset_root,
                final_candidate=final_candidate,
                final_preexisting=final_preexisting,
                latest_preexisting=latest_preexisting,
                latest_bytes=latest_bytes,
                dataset_version=dataset_version,
            )
            raise M10SnapshotExportFailure("acceptance") from None
        return M10SnapshotResult(status="published", metrics=projection.metrics, digest=digest, dataset_version=dataset_version, final_path=final_path)


M10SnapshotExporter = ExportM10Snapshot
M10FullSnapshotExporter = ExportM10Snapshot
M10SnapshotExportError = M10SnapshotExportFailure
ExportM10SnapshotUseCase = ExportM10Snapshot

__all__ = [
    "ExportM10Snapshot", "ExportM10SnapshotUseCase", "M10SnapshotExporter",
    "M10FullSnapshotExporter", "M10SnapshotExportFailure", "M10SnapshotExportError",
    "M10SnapshotExportFailureCategory",
]
