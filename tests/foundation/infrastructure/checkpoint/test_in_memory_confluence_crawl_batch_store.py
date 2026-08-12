import pytest
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import BatchCheckpoint, BatchFailureCategory, BatchMetrics, BatchState
from knowledgenexus.foundation.infrastructure.checkpoint.in_memory_confluence_crawl_batch_store import InMemoryConfluenceCrawlBatchStore
from tests.foundation.domain.models.test_confluence_crawl_batch import request

def test_lease_cas_commit_and_stale_rejection():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=10)
    committed = store.commit(lease, batch_digest="d" * 64, metrics=BatchMetrics(1, 1, 1, 0, 0), now=0)
    assert committed.state is BatchState.COMMITTED
    assert store.commit(lease, batch_digest="d" * 64, metrics=BatchMetrics(1, 1, 1, 0, 0), now=0) == committed

def test_expired_lease_can_be_reclaimed_and_wrong_token_fails_closed():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    with pytest.raises(Exception): store.claim(req.batch_id, token="x", now=0, lease_seconds=1)
    lease2 = store.claim(req.batch_id, token="x", now=2, lease_seconds=1)
    with pytest.raises(Exception): store.commit(lease, batch_digest="d", metrics=BatchMetrics(1, 1, 1, 0, 0))
    assert lease2.attempt == 2

def test_commit_at_expiry_is_rejected():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    with pytest.raises(Exception): store.commit(lease, batch_digest="d" * 64, metrics=BatchMetrics(1, 1, 1, 0, 0), now=1)

def test_reclaim_requires_new_token():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    with pytest.raises(Exception): store.claim(req.batch_id, token="t", now=1, lease_seconds=1)
    assert store.claim(req.batch_id, token="new", now=1, lease_seconds=1).attempt == 2

def test_fail_requires_live_matching_lease_and_now():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    failed = store.fail(lease, category=BatchFailureCategory.TRANSPORT, now=0.5)
    assert failed.state is BatchState.FAILED

def test_fail_rejects_expired_and_reclaimed_leases():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    with pytest.raises(Exception):
        store.fail(lease, category=BatchFailureCategory.TRANSPORT, now=1)
    lease2 = store.claim(req.batch_id, token="new", now=2, lease_seconds=1)
    with pytest.raises(Exception):
        store.fail(lease, category=BatchFailureCategory.TRANSPORT, now=2)
    assert lease2.attempt == 2

def test_requeue_requires_finite_now_and_live_exact_lease():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="t", now=0, lease_seconds=1)
    for malformed in (object(), None, True, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            store.requeue(lease, category=BatchFailureCategory.TRANSPORT, now=malformed)
    pending = store.requeue(lease, category=BatchFailureCategory.TRANSPORT, now=0.5)
    assert pending.state is BatchState.PENDING and pending.attempt == 1

def test_requeue_rejects_expired_and_reclaimed_stale_workers():
    store = InMemoryConfluenceCrawlBatchStore(); req = request(); store.create(BatchCheckpoint(req))
    lease = store.claim(req.batch_id, token="old", now=0, lease_seconds=1)
    with pytest.raises(Exception):
        store.requeue(lease, category=BatchFailureCategory.TRANSPORT, now=1)
    lease2 = store.claim(req.batch_id, token="new", now=2, lease_seconds=1)
    with pytest.raises(Exception):
        store.requeue(lease, category=BatchFailureCategory.TRANSPORT, now=2)
    assert store.get(req.batch_id).lease == lease2 and store.get(req.batch_id).attempt == 2
