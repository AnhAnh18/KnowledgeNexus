from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionRequest,
    ConfluenceRawPageOrphanInspectionResult,
)


class ConfluenceRawPageOrphanInspectionPort(Protocol):
    """Read-only operation boundary for inspecting one raw-page artifact."""

    def inspect_raw_page(
        self,
        *,
        request: ConfluenceRawPageOrphanInspectionRequest,
    ) -> ConfluenceRawPageOrphanInspectionResult: ...

    def inspect_orphan(
        self,
        *,
        request: ConfluenceRawPageOrphanInspectionRequest,
    ) -> ConfluenceRawPageOrphanInspectionResult: ...


__all__ = ["ConfluenceRawPageOrphanInspectionPort"]
