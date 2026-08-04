from __future__ import annotations

import stat
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
)
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_orphan_inspection import (
    ConfluenceRawRestrictionOrphanInspectionDecision,
    ConfluenceRawRestrictionOrphanInspectionError,
    ConfluenceRawRestrictionOrphanInspectionFailureCategory,
    ConfluenceRawRestrictionOrphanInspectionRequest,
    ConfluenceRawRestrictionOrphanInspectionResult,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _MAX_STABLE_READ_BYTES,
    _bound_read,
    _bound_stat,
    _is_link_or_reparse,
    _metadata,
    _open_bound_parent,
    ConfluenceRawRestrictionEvidenceStore,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_orphan_inspection_port import (
    ConfluenceRawRestrictionOrphanInspectionPort,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_store_port import (
    ConfluenceRawRestrictionStoreError,
)


class ConfluenceRawRestrictionOrphanInspector(
    ConfluenceRawRestrictionOrphanInspectionPort
):
    """Inspects one existing restriction artifact without filesystem mutation."""

    def __init__(self, *, raw_root: Path) -> None:
        try:
            self._restriction_store = ConfluenceRawRestrictionEvidenceStore(
                raw_root=raw_root
            )
        except (ConfluenceRawRestrictionStoreError, OSError, TypeError, ValueError):
            raise ConfluenceRawRestrictionOrphanInspectionError(
                ConfluenceRawRestrictionOrphanInspectionFailureCategory.RAW_ROOT_INVALID
            ) from None

    def inspect_restriction(
        self,
        *,
        request: ConfluenceRawRestrictionOrphanInspectionRequest,
    ) -> ConfluenceRawRestrictionOrphanInspectionResult:
        if type(request) is not ConfluenceRawRestrictionOrphanInspectionRequest:
            raise ConfluenceRawRestrictionOrphanInspectionError(
                ConfluenceRawRestrictionOrphanInspectionFailureCategory.INVALID_REQUEST
            )

        try:
            target = self._restriction_store.resolve_restriction_path(
                run_id=request.run_id,
                selected_page_id=request.selected_page_id,
                target_page_id=request.target_page_id,
            )
        except Exception:
            raise ConfluenceRawRestrictionOrphanInspectionError(
                ConfluenceRawRestrictionOrphanInspectionFailureCategory.INSPECTION_FAILED
            ) from None

        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                try:
                    details = _bound_stat(parent_handle, target.name)
                except FileNotFoundError:
                    return ConfluenceRawRestrictionOrphanInspectionResult(
                        decision=ConfluenceRawRestrictionOrphanInspectionDecision.MISSING
                    )
                except (OSError, TypeError, ValueError):
                    return ConfluenceRawRestrictionOrphanInspectionResult(
                        decision=ConfluenceRawRestrictionOrphanInspectionDecision.UNSAFE_TARGET
                    )
                if (
                    _is_link_or_reparse(details)
                    or not stat.S_ISREG(details.st_mode)
                    or details.st_size > _MAX_STABLE_READ_BYTES
                ):
                    return ConfluenceRawRestrictionOrphanInspectionResult(
                        decision=ConfluenceRawRestrictionOrphanInspectionDecision.UNSAFE_TARGET
                    )
                try:
                    content = _bound_read(
                        parent_handle,
                        target.name,
                        expected_metadata=_metadata(details),
                    )
                except FileNotFoundError:
                    return ConfluenceRawRestrictionOrphanInspectionResult(
                        decision=ConfluenceRawRestrictionOrphanInspectionDecision.UNSAFE_TARGET
                    )
        except FileNotFoundError:
            return ConfluenceRawRestrictionOrphanInspectionResult(
                decision=ConfluenceRawRestrictionOrphanInspectionDecision.MISSING
            )
        except (OverflowError, OSError, TypeError, ValueError):
            return ConfluenceRawRestrictionOrphanInspectionResult(
                decision=ConfluenceRawRestrictionOrphanInspectionDecision.UNSAFE_TARGET
            )
        except Exception:
            raise ConfluenceRawRestrictionOrphanInspectionError(
                ConfluenceRawRestrictionOrphanInspectionFailureCategory.INSPECTION_FAILED
            ) from None

        try:
            envelope = ConfluenceRestrictionEvidenceEnvelope.from_bytes(content)
        except Exception:
            return ConfluenceRawRestrictionOrphanInspectionResult(
                decision=ConfluenceRawRestrictionOrphanInspectionDecision.INVALID
            )

        if (
            envelope.request_profile_version != request.request_profile_version
            or envelope.selected_page_id != request.selected_page_id
            or envelope.target_page_id != request.target_page_id
        ):
            return ConfluenceRawRestrictionOrphanInspectionResult(
                decision=ConfluenceRawRestrictionOrphanInspectionDecision.IDENTITY_CONFLICT
            )

        return ConfluenceRawRestrictionOrphanInspectionResult(
            decision=ConfluenceRawRestrictionOrphanInspectionDecision.REPLAYABLE,
            envelope=envelope,
        )


__all__ = ["ConfluenceRawRestrictionOrphanInspector"]
