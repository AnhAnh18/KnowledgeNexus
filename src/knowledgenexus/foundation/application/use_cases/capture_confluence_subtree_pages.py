"""Production-composed, page-granular raw capture for a bounded root."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_raw_page_generation import (
    FetchAndStoreConfluenceRawPageGeneration, GenerationRawPageFetchError,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_crawl_run import InventoryRootCommit
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import ConfluenceRawPageOrphanInspectionRequest
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    RawPageAcknowledgement, RawPageReplayCommand, RawPageReplayDecision, RawPageReplayFailure,
    RawPageReplayResult,
)


_FETCH_FAILURE_CATEGORIES = frozenset({
    "invalid_run_id",
    "invalid_page_id",
    "http",
    "response_size_limit",
    "malformed_json",
    "non_object_json",
    "identity_mismatch",
    "source_version_invalid",
    "store",
})
_REPLAY_FAILURE_CATEGORIES = frozenset({
    "invalid_request",
    "inspection_failed",
    "schema_incompatible",
})
_REPLAY_REJECTION_DECISIONS = frozenset({
    RawPageReplayDecision.CONFLICT,
    RawPageReplayDecision.INVALID,
    RawPageReplayDecision.IDENTITY_CONFLICT,
    RawPageReplayDecision.UNSAFE_TARGET,
    RawPageReplayDecision.UNKNOWN_INVENTORY,
})
_ACK_REJECTION_DECISIONS = frozenset({
    RawPageReplayDecision.CONFLICT,
    RawPageReplayDecision.INVALID,
    RawPageReplayDecision.IDENTITY_CONFLICT,
    RawPageReplayDecision.UNSAFE_TARGET,
    RawPageReplayDecision.UNKNOWN_INVENTORY,
    RawPageReplayDecision.MISSING,
})


def _allowed_failure_categories() -> frozenset[str]:
    return frozenset(
        {f"fetch_{category}" for category in _FETCH_FAILURE_CATEGORIES}
        | {f"replay_{category}" for category in _REPLAY_FAILURE_CATEGORIES}
        | {f"acknowledgement_{category}" for category in _REPLAY_FAILURE_CATEGORIES}
        | {f"replay_{decision.value}" for decision in _REPLAY_REJECTION_DECISIONS}
        | {f"acknowledgement_{decision.value}" for decision in _ACK_REJECTION_DECISIONS}
        | {
            "fetch_failure_invalid",
            "replay_result_invalid",
            "acknowledgement_result_invalid",
        }
    )


PAGE_CAPTURE_FAILURE_CATEGORIES = _allowed_failure_categories()


@dataclass(frozen=True)
class PageCaptureResult:
    captured: int
    replayed: int
    skipped: int
    failed: int
    stopped: bool
    expected_total: int = -1
    failure_categories: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not PageCaptureResult:
            raise TypeError("capture result type is invalid")
        values = (self.captured, self.replayed, self.skipped, self.failed)
        if any(type(v) is not int or v < 0 for v in values) or type(self.stopped) is not bool:
            raise ValueError("invalid capture result")
        if type(self.expected_total) is not int or self.expected_total < 0:
            raise ValueError("invalid expected total")
        if sum(values) > self.expected_total:
            raise ValueError("capture counters exceed selected total")
        if type(self.failure_categories) is not tuple:
            raise TypeError("failure categories are invalid")
        previous = None
        observed_failures = 0
        for entry in self.failure_categories:
            if type(entry) is not tuple or len(entry) != 2:
                raise TypeError("failure category entry is invalid")
            category, count = entry
            if type(category) is not str or category not in PAGE_CAPTURE_FAILURE_CATEGORIES:
                raise ValueError("failure category is invalid")
            if type(count) is not int or count <= 0:
                raise ValueError("failure category count is invalid")
            if previous is not None and category <= previous:
                raise ValueError("failure categories are not canonical")
            previous = category
            observed_failures += count
        if observed_failures != self.failed:
            raise ValueError("failure category counts do not match failed")
        if not self.stopped and (
            self.failed != 0
            or self.captured + self.replayed + self.skipped != self.expected_total
        ):
            raise ValueError("non-stopped capture result is incomplete")

    @property
    def complete(self) -> bool:
        return not self.stopped and self.failed == 0 and (
            self.captured + self.replayed + self.skipped == self.expected_total
        )


class CaptureConfluenceSubtreePages:
    """Capture pages in deterministic inventory order using approved M7 seams."""

    def __init__(self, *, state_session: object, orphan_inspector: object,
                 page_fetcher: object, raw_page_store: object,
                 max_pages: int | None = None) -> None:
        for name in ("replay_raw_page", "acknowledge_raw_page"):
            if not callable(getattr(state_session, name, None)):
                raise TypeError("state_session is invalid")
        if not callable(getattr(orphan_inspector, "inspect_raw_page", None)):
            raise TypeError("orphan_inspector is invalid")
        if not callable(getattr(raw_page_store, "read_page", None)):
            raise TypeError("raw_page_store is invalid")
        if max_pages is not None and (type(max_pages) is not int or max_pages <= 0):
            raise ValueError("max_pages is invalid")
        self._state = state_session
        self._inspector = orphan_inspector
        self._raw_store = raw_page_store
        self._max_pages = max_pages
        self._fetch = FetchAndStoreConfluenceRawPageGeneration(
            page_fetcher=page_fetcher, raw_page_store=raw_page_store
        )

    def run(self, *, run_id: CrawlRunId, occurrences: Iterable[InventoryRootCommit | InventoryOccurrence],
            stop_after: int | None = None, stop_after_batches: int | None = None) -> PageCaptureResult:
        if type(run_id) is not CrawlRunId:
            raise TypeError("run_id is invalid")
        items = tuple(occurrences)
        if any(type(item) not in (InventoryRootCommit, InventoryOccurrence) for item in items):
            raise TypeError("occurrences are invalid")
        if self._max_pages is not None and len(items) > self._max_pages:
            raise ValueError("occurrences exceed page budget")
        page_ids = tuple(item.metadata.page_id for item in items)
        if len(set(page_ids)) != len(page_ids):
            raise ValueError("occurrences contain duplicate pages")
        if stop_after is not None and (type(stop_after) is not int or stop_after < 0):
            raise ValueError("stop_after is invalid")
        if stop_after_batches is not None and (type(stop_after_batches) is not int or stop_after_batches < 0):
            raise ValueError("stop_after_batches is invalid")
        if stop_after is not None and stop_after_batches is not None:
            raise ValueError("stop limits are ambiguous")
        batch_limit = stop_after_batches if stop_after_batches is not None else stop_after
        captured = replayed = skipped = failed = 0
        failure_categories: Counter[str] = Counter()

        def record_failure(category: str) -> None:
            nonlocal failed
            if category not in PAGE_CAPTURE_FAILURE_CATEGORIES:
                raise ValueError("unknown page capture failure category")
            failed += 1
            failure_categories[category] += 1

        def build_result(*, stopped: bool) -> PageCaptureResult:
            return PageCaptureResult(
                captured,
                replayed,
                skipped,
                failed,
                stopped,
                len(items),
                tuple(sorted(failure_categories.items())),
            )

        if batch_limit == 0:
            return build_result(stopped=True)
        batches_done = 0
        for batch_start in range(0, len(items), 100):
            batch_pending = False
            batch_failed = False
            for occurrence in items[batch_start:batch_start + 100]:
                page_id = occurrence.metadata.page_id
                request = ConfluenceRawPageOrphanInspectionRequest.capture(
                    run_id=run_id, generation_id=run_id,
                    page_id=page_id, source_version=occurrence.metadata.source_version,
                )
                outcome = self._state.replay_raw_page(RawPageReplayCommand(request), self._inspector)
                if type(outcome) is RawPageReplayFailure:
                    record_failure(f"replay_{outcome.category.value}")
                    batch_failed = True
                    continue
                if type(outcome) is not RawPageReplayResult:
                    record_failure("replay_result_invalid")
                    batch_failed = True
                    continue
                if outcome.decision in (RawPageReplayDecision.REPLAYED, RawPageReplayDecision.COMMITTED):
                    replayed += 1; continue
                if outcome.decision is not RawPageReplayDecision.MISSING:
                    record_failure(f"replay_{outcome.decision.value}")
                    batch_failed = True
                    continue
                batch_pending = True
                try:
                    fetch_result = self._fetch.execute(run_id=run_id, page_id=page_id)
                    envelope = self._raw_store.read_page(run_id=run_id, page_id=page_id)
                    ack = self._state.acknowledge_raw_page(
                        RawPageAcknowledgement(
                            envelope=envelope,
                            artifact=fetch_result.artifact,
                        )
                    )
                    if type(ack) is RawPageReplayFailure:
                        record_failure(f"acknowledgement_{ack.category.value}")
                        batch_failed = True
                    elif type(ack) is not RawPageReplayResult:
                        record_failure("acknowledgement_result_invalid")
                        batch_failed = True
                    elif ack.decision not in (RawPageReplayDecision.COMMITTED, RawPageReplayDecision.REPLAYED):
                        record_failure(f"acknowledgement_{ack.decision.value}")
                        batch_failed = True
                    else:
                        captured += 1
                except GenerationRawPageFetchError as exc:
                    category = (
                        f"fetch_{exc.category}"
                        if exc.category in _FETCH_FAILURE_CATEGORIES
                        else "fetch_failure_invalid"
                    )
                    record_failure(category)
                    batch_failed = True
            if batch_pending:
                batches_done += 1
            if batch_failed or (
                batch_pending
                and batch_limit is not None
                and batches_done >= batch_limit
            ):
                return build_result(stopped=True)
        return build_result(stopped=False)


__all__ = [
    "CaptureConfluenceSubtreePages",
    "PAGE_CAPTURE_FAILURE_CATEGORIES",
    "PageCaptureResult",
]
