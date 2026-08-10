"""Production-composed, page-granular raw capture for a bounded root."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_raw_page_generation import (
    FetchAndStoreConfluenceRawPageGeneration,
    GenerationRawPageFetchError,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    RawPageAcknowledgement,
    RawPageReplayCommand,
    RawPageReplayDecision,
    RawPageReplayFailure,
)


@dataclass(frozen=True)
class PageCaptureResult:
    captured: int
    replayed: int
    skipped: int
    failed: int
    stopped: bool

    def __post_init__(self) -> None:
        values = (self.captured, self.replayed, self.skipped, self.failed)
        if any(type(v) is not int or v < 0 for v in values) or type(self.stopped) is not bool:
            raise ValueError("invalid capture result")


class CaptureConfluenceSubtreePages:
    """Capture pages in deterministic inventory order using approved M7 seams."""

    def __init__(self, *, state_session: object, orphan_inspector: object,
                 page_fetcher: object, raw_page_store: object) -> None:
        for name in ("replay_raw_page", "acknowledge_raw_page"):
            if not callable(getattr(state_session, name, None)):
                raise TypeError("state_session is invalid")
        if not callable(getattr(orphan_inspector, "inspect_raw_page", None)):
            raise TypeError("orphan_inspector is invalid")
        self._state = state_session
        self._inspector = orphan_inspector
        self._fetch = FetchAndStoreConfluenceRawPageGeneration(
            page_fetcher=page_fetcher, raw_page_store=raw_page_store
        )

    def run(self, *, run_id: CrawlRunId, occurrences: Iterable[InventoryOccurrence],
            stop_after: int | None = None, stop_after_batches: int | None = None) -> PageCaptureResult:
        if type(run_id) is not CrawlRunId:
            raise TypeError("run_id is invalid")
        items = tuple(occurrences)
        if any(type(item) is not InventoryOccurrence for item in items):
            raise TypeError("occurrences are invalid")
        if stop_after is not None and (type(stop_after) is not int or stop_after < 0):
            raise ValueError("stop_after is invalid")
        if stop_after_batches is not None and (type(stop_after_batches) is not int or stop_after_batches < 0):
            raise ValueError("stop_after_batches is invalid")
        if stop_after is not None and stop_after_batches is not None:
            raise ValueError("stop limits are ambiguous")
        batch_limit = stop_after_batches if stop_after_batches is not None else stop_after
        page_limit = None if batch_limit is None else batch_limit * 100
        captured = replayed = skipped = failed = 0
        for index, occurrence in enumerate(items):
            if page_limit is not None and index >= page_limit:
                return PageCaptureResult(captured, replayed, skipped, failed, True)
            source_version = occurrence.metadata.source_version
            request = ConfluenceRawPageOrphanInspectionRequest.capture(
                run_id=run_id, generation_id=run_id,
                page_id=occurrence.page_id, source_version=source_version,
            )
            outcome = self._state.replay_raw_page(
                RawPageReplayCommand(request), self._inspector
            )
            if isinstance(outcome, RawPageReplayFailure):
                failed += 1
                continue
            if outcome.decision in (RawPageReplayDecision.REPLAYED, RawPageReplayDecision.COMMITTED):
                replayed += 1
                continue
            if outcome.decision is not RawPageReplayDecision.MISSING:
                failed += 1
                continue
            try:
                result = self._fetch.execute(run_id=run_id, page_id=occurrence.page_id)
                ack = self._state.acknowledge_raw_page(
                    RawPageAcknowledgement(
                        envelope=self._read_envelope(result.artifact),
                        artifact=result.artifact,
                    )
                )
                if isinstance(ack, RawPageReplayFailure) or ack.decision not in (
                    RawPageReplayDecision.COMMITTED, RawPageReplayDecision.REPLAYED
                ):
                    failed += 1
                else:
                    captured += 1
            except GenerationRawPageFetchError:
                failed += 1
        return PageCaptureResult(captured, replayed, skipped, failed, False)

    @staticmethod
    def _read_envelope(artifact):
        from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import ConfluenceRawPageEnvelope
        try:
            return ConfluenceRawPageEnvelope.from_bytes(artifact.path.read_bytes())
        except Exception:
            raise GenerationRawPageFetchError("store")


__all__ = ["CaptureConfluenceSubtreePages", "PageCaptureResult"]
