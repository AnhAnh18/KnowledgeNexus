from __future__ import annotations

import stat
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionDecision,
    ConfluenceRawPageOrphanInspectionError,
    ConfluenceRawPageOrphanInspectionFailureCategory,
    ConfluenceRawPageOrphanInspectionRequest,
    ConfluenceRawPageOrphanInspectionResult,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_generation_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _MAX_STABLE_READ_BYTES,
    _bound_read,
    _bound_stat,
    _is_link_or_reparse,
    _metadata,
    _open_bound_parent,
)
from knowledgenexus.foundation.ports.confluence_raw_page_orphan_inspection_port import (
    ConfluenceRawPageOrphanInspectionPort,
)


class ConfluenceRawPageOrphanInspector(ConfluenceRawPageOrphanInspectionPort):
    """Inspects one existing D3 raw-page artifact without filesystem mutation."""

    def __init__(self, *, raw_root: Path) -> None:
        try:
            self._generation_store = ConfluenceRawPageGenerationStore(raw_root=raw_root)
        except ConfluenceRawPageStoreError:
            raise ConfluenceRawPageOrphanInspectionError(
                ConfluenceRawPageOrphanInspectionFailureCategory.RAW_ROOT_INVALID
            ) from None

    def inspect_raw_page(
        self,
        *,
        request: ConfluenceRawPageOrphanInspectionRequest,
    ) -> ConfluenceRawPageOrphanInspectionResult:
        if type(request) is not ConfluenceRawPageOrphanInspectionRequest:
            raise ConfluenceRawPageOrphanInspectionError(
                ConfluenceRawPageOrphanInspectionFailureCategory.INVALID_REQUEST
            )

        target = self._generation_store.resolve_page_path(
            run_id=request.run_id,
            page_id=request.page_id,
        )
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                try:
                    details = _bound_stat(parent_handle, target.name)
                except FileNotFoundError:
                    return ConfluenceRawPageOrphanInspectionResult(
                        decision=ConfluenceRawPageOrphanInspectionDecision.MISSING
                    )
                except (OSError, TypeError, ValueError):
                    return ConfluenceRawPageOrphanInspectionResult(
                        decision=ConfluenceRawPageOrphanInspectionDecision.UNSAFE_TARGET
                    )
                if (
                    _is_link_or_reparse(details)
                    or not stat.S_ISREG(details.st_mode)
                    or details.st_size > _MAX_STABLE_READ_BYTES
                ):
                    return ConfluenceRawPageOrphanInspectionResult(
                        decision=ConfluenceRawPageOrphanInspectionDecision.UNSAFE_TARGET
                    )
                try:
                    content = _bound_read(
                        parent_handle,
                        target.name,
                        expected_metadata=_metadata(details),
                    )
                except FileNotFoundError:
                    # The target existed during the bound stat, so disappearance
                    # is an unstable race rather than an absent artifact.
                    return ConfluenceRawPageOrphanInspectionResult(
                        decision=ConfluenceRawPageOrphanInspectionDecision.UNSAFE_TARGET
                    )
        except FileNotFoundError:
            return ConfluenceRawPageOrphanInspectionResult(
                decision=ConfluenceRawPageOrphanInspectionDecision.MISSING
            )
        except (OverflowError, OSError, TypeError, ValueError):
            return ConfluenceRawPageOrphanInspectionResult(
                decision=ConfluenceRawPageOrphanInspectionDecision.UNSAFE_TARGET
            )

        try:
            envelope = ConfluenceRawPageEnvelope.from_bytes(content)
        except Exception:
            return ConfluenceRawPageOrphanInspectionResult(
                decision=ConfluenceRawPageOrphanInspectionDecision.INVALID
            )

        if (
            envelope.request_profile_version != request.request_profile_version
            or envelope.run_id != request.run_id
            or envelope.generation_id != request.generation_id
            or envelope.page_id != request.page_id
            or envelope.source_version != request.source_version
        ):
            return ConfluenceRawPageOrphanInspectionResult(
                decision=ConfluenceRawPageOrphanInspectionDecision.IDENTITY_CONFLICT
            )

        return ConfluenceRawPageOrphanInspectionResult(
            decision=ConfluenceRawPageOrphanInspectionDecision.REPLAYABLE,
            envelope=envelope,
        )

    def inspect_orphan(
        self,
        *,
        request: ConfluenceRawPageOrphanInspectionRequest,
    ) -> ConfluenceRawPageOrphanInspectionResult:
        """Named alias for callers that use the orphan-inspection operation."""

        return self.inspect_raw_page(request=request)


__all__ = ["ConfluenceRawPageOrphanInspector"]
