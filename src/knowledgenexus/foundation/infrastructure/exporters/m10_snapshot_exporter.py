"""Concrete M10 exporter wiring for the shared M3 filesystem seams."""
from __future__ import annotations

from knowledgenexus.foundation.application.use_cases.export_m10_snapshot import (
    ExportM10Snapshot,
)
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_publisher import M10SnapshotPublisher
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_completer import FullSnapshotStagingCompleter
from knowledgenexus.foundation.infrastructure.exporters.full_snapshot_staging_writer import FullSnapshotStagingWriter


class M10FullSnapshotExporter(ExportM10Snapshot):
    def __init__(self, **kwargs: object) -> None:
        # Keep the production seams as defaults while allowing tests and
        # embedders to replace one seam without triggering duplicate kwargs.
        kwargs.setdefault("staging_writer", FullSnapshotStagingWriter)
        kwargs.setdefault("staging_completer", FullSnapshotStagingCompleter)
        kwargs.setdefault("publisher", M10SnapshotPublisher)
        super().__init__(**kwargs)


__all__ = ["M10FullSnapshotExporter"]
