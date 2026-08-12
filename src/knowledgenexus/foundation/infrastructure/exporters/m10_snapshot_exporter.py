"""Concrete M10 exporter wiring for the shared M3 filesystem seams."""
from __future__ import annotations

from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import (
    ExportM10Snapshot,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher import M10SnapshotPublisher
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import FullSnapshotStagingCompleter
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import FullSnapshotStagingWriter
from knowledgenexus.foundation.application.use_cases.project_m10_delta import M10DeltaOrchestrator
from knowledgenexus.foundation.domain.models.delta_propagation import DeltaInventoryEntry
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


class M10FullSnapshotExporter(ExportM10Snapshot):
    def __init__(self, **kwargs: object) -> None:
        # Keep the production seams as defaults while allowing tests and
        # embedders to replace one seam without triggering duplicate kwargs.
        kwargs.setdefault("staging_writer", FullSnapshotStagingWriter)
        kwargs.setdefault("staging_completer", FullSnapshotStagingCompleter)
        kwargs.setdefault("publisher", M10SnapshotPublisher)
        super().__init__(**kwargs)


class M10DeltaSnapshotExporter(ExportM10Snapshot):
    """Export a delta after diffing the current projection with a prior reader."""

    def __init__(self, *, prior_snapshot_reader: object, schema_validator: FoundationSchemaValidator | None = None, delta_inventory: tuple[DeltaInventoryEntry, ...] = (), **kwargs: object) -> None:
        if "delta_orchestrator" in kwargs:
            raise TypeError("delta_orchestrator is owned by M10DeltaSnapshotExporter")
        validator = schema_validator if schema_validator is not None else FoundationSchemaValidator()
        kwargs.setdefault("schema_validator", validator)
        kwargs.setdefault("staging_writer", FullSnapshotStagingWriter)
        kwargs.setdefault("staging_completer", FullSnapshotStagingCompleter)
        kwargs.setdefault("publisher", M10SnapshotPublisher)
        kwargs["delta_orchestrator"] = M10DeltaOrchestrator(
            prior_snapshot_reader=prior_snapshot_reader,
            schema_validator=validator,
        )
        kwargs["delta_inventory"] = delta_inventory
        super().__init__(**kwargs)


__all__ = ["M10FullSnapshotExporter", "M10DeltaSnapshotExporter"]
