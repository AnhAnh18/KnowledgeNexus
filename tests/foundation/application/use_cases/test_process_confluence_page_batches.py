import pytest
from knowledgenexus.foundation.domain.models import CrawlRunId, CanonicalIncludeRoots, ConfluencePageMetadata, InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import BatchCheckpoint
from knowledgenexus.foundation.application.use_cases.process_confluence_page_batches import ProcessConfluencePageBatches, BatchRunConfig
from knowledgenexus.foundation.infrastructure.checkpoint.in_memory_confluence_crawl_batch_store import InMemoryConfluenceCrawlBatchStore

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000"); ROOTS = CanonicalIncludeRoots(("root",))
def occurrences(count=2):
    return tuple(InventoryOccurrence(RUN, 0, "root", 0, n, f"page-{n}", ConfluencePageMetadata(f"page-{n}", "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",)), ROOTS) for n in range(count))
class Fetch:
    def __init__(self, fail=0): self.calls = 0; self.fail = fail
    def fetch_page_raw(self, *, page_id):
        self.calls += 1
        if self.calls <= self.fail: raise RuntimeError("transport")
        return page_id.encode()

class EstimatingFetch(Fetch):
    def estimate_page_bytes(self, *, page_id): return len(page_id)

def test_partition_is_deterministic_and_default_is_100():
    reqs = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(201))
    assert [len(x.occurrences) for x in reqs] == [100, 100, 1]
    assert [x.batch_id for x in reqs] == [x.batch_id for x in ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(201))]

def test_retry_then_commit_and_resume_does_not_refetch():
    fetch = Fetch(fail=1); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(2))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=2))
    assert result.committed == 1 and result.retries == 1 and fetch.calls == 3
    again = driver.run((req,), config=BatchRunConfig(max_attempts=2))
    assert again.committed == 1 and fetch.calls == 3

def test_malformed_processor_is_terminal_and_result_is_sanitized():
    fetch = Fetch(); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, process_page_set=lambda _: (_ for _ in ()).throw(ValueError("secret")), clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=1))
    assert result.failed == 1 and result.committed == 0 and "secret" not in result.digest
    assert store.get(req.batch_id).failure_category.value == "malformed"

def test_failed_checkpoint_reentry_is_terminal_and_does_not_refetch_or_process():
    fetch = Fetch(); processed = []
    store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(
        store=store,
        fetcher=fetch,
        process_page_set=lambda pages: processed.append(pages),
        clock=lambda: 0,
        token_factory=lambda _: "token",
    )
    req = ProcessConfluencePageBatches.partition(
        run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i",
        occurrences=occurrences(1),
    )[0]
    # Seed a terminal failure, then verify both re-entry and repeated re-entry
    # are deterministic and have no side effects.
    failing = ProcessConfluencePageBatches(
        store=store,
        fetcher=fetch,
        process_page_set=lambda _: (_ for _ in ()).throw(ValueError("bad")),
        clock=lambda: 0,
        token_factory=lambda _: "token",
    )
    first = failing.run((req,), config=BatchRunConfig(max_attempts=1))
    assert first.failed == 1 and first.committed == 0
    calls_after_failure = fetch.calls
    second = driver.run((req,), config=BatchRunConfig(max_attempts=1))
    third = driver.run((req,), config=BatchRunConfig(max_attempts=1))
    assert second == third == first
    assert fetch.calls == calls_after_failure
    assert processed == []

def test_mixed_committed_and_failed_resume_has_canonical_totals():
    fetch = Fetch(); store = InMemoryConfluenceCrawlBatchStore()
    reqs = ProcessConfluencePageBatches.partition(
        run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i",
        occurrences=occurrences(2), batch_size=1,
    )
    failing = ProcessConfluencePageBatches(
        store=store,
        fetcher=fetch,
        process_page_set=lambda _: (_ for _ in ()).throw(ValueError("bad")),
        clock=lambda: 0,
        token_factory=lambda _: "token",
    )
    failing.run((reqs[0],), config=BatchRunConfig(max_attempts=1))
    succeeding = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    first = succeeding.run((reqs[0], reqs[1]), config=BatchRunConfig(max_attempts=1))
    second = succeeding.run((reqs[0], reqs[1]), config=BatchRunConfig(max_attempts=1))
    assert first == second
    assert (first.committed, first.failed, first.total_batches) == (1, 1, 2)
    assert first.page_count == 1 and first.byte_count == len("page-1") and first.total_requests == 1

def test_request_budget_is_terminal_before_extra_fetch():
    fetch = Fetch(); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(2))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=1, max_requests=1))
    assert result.failed == 1 and fetch.calls == 1

def test_global_byte_budget_stops_before_next_page_with_estimator():
    fetch = EstimatingFetch(); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(2))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=1, max_bytes=6))
    assert result.failed == 1 and fetch.calls == 1

def test_estimator_enforces_page_and_global_budgets_conjunctively_before_fetch():
    fetch = EstimatingFetch(); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    # The page fits the per-page limit but not the run-wide limit; transport
    # must not be called when both known estimates are evaluated.
    result = driver.run((req,), config=BatchRunConfig(max_attempts=1, max_page_bytes=100, max_bytes=5))
    assert result.failed == 1 and fetch.calls == 0

def test_expired_retry_requeue_cannot_reset_attempt_or_reclaim_same_token():
    fetch = Fetch(fail=1); store = InMemoryConfluenceCrawlBatchStore()
    times = iter((0, 2, 3))
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: next(times), token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    with pytest.raises(Exception):
        driver.run((req,), config=BatchRunConfig(max_attempts=2, lease_seconds=1))
    checkpoint = store.get(req.batch_id)
    assert checkpoint.state.value == "leased" and checkpoint.attempt == 1

def test_result_rejects_forged_digest_and_resume_restores_metrics():
    fetch = Fetch(); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    first = driver.run((req,)); second = driver.run((req,))
    assert first.page_count == second.page_count and first.byte_count == second.byte_count and fetch.calls == 1
    with pytest.raises(ValueError):
        from knowledgenexus.foundation.application.use_cases.process_confluence_page_batches import BatchRunResult
        BatchRunResult(1, 0, 0, 1, 1, 1, "x", 1, 1, 1, 1, 0)

def test_retry_budget_exhaustion_does_not_fetch_again():
    fetch = Fetch(fail=9); store = InMemoryConfluenceCrawlBatchStore()
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=3, max_requests=1))
    assert result.failed == 1 and fetch.calls == 1

def test_failed_attempt_bytes_count_toward_retry_budget():
    fetch = EstimatingFetch(); store = InMemoryConfluenceCrawlBatchStore(); calls = 0
    def process(_pages):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient processor failure")
    driver = ProcessConfluencePageBatches(store=store, fetcher=fetch, process_page_set=process, clock=lambda: 0, token_factory=lambda _: "token")
    req = ProcessConfluencePageBatches.partition(run_id=str(RUN), generation_digest="g", config_digest="c", inventory_digest="i", occurrences=occurrences(1))[0]
    result = driver.run((req,), config=BatchRunConfig(max_attempts=2, max_bytes=len("page-0")))
    assert result.failed == 1 and fetch.calls == 1 and calls == 1
