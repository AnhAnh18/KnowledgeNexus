from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_raw_restriction_orphan_inspection import (
    ConfluenceRawRestrictionOrphanInspectionRequest,
    ConfluenceRawRestrictionOrphanInspectionResult,
)


class ConfluenceRawRestrictionOrphanInspectionPort(Protocol):
    """Read-only operation boundary for inspecting restriction evidence."""

    def inspect_restriction(
        self,
        *,
        request: ConfluenceRawRestrictionOrphanInspectionRequest,
    ) -> ConfluenceRawRestrictionOrphanInspectionResult: ...


__all__ = ["ConfluenceRawRestrictionOrphanInspectionPort"]
