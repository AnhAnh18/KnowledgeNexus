"""Concrete M10 exporter wiring for the shared M3 filesystem seams."""
from __future__ import annotations

from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import (
    ExportM10Snapshot,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher import FullSnapshotPublisher
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import FullSnapshotStagingCompleter
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import FullSnapshotStagingWriter


class M10FullSnapshotExporter(ExportM10Snapshot):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            staging_writer=FullSnapshotStagingWriter,
            staging_completer=FullSnapshotStagingCompleter,
            publisher=FullSnapshotPublisher,
            **kwargs,
        )


__all__ = ["M10FullSnapshotExporter"]
