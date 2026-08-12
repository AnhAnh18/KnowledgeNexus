import pytest
from knowledgenexus.foundation.domain.models import CrawlRunId, CanonicalIncludeRoots, ConfluencePageMetadata, InventoryOccurrence
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import BatchCheckpoint, BatchRequest, BatchState, BatchMetrics, BatchLease

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
ROOTS = CanonicalIncludeRoots(("root",))
def occ(page="page"):
    meta = ConfluencePageMetadata(page, "Page", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))
    return InventoryOccurrence(RUN, 0, "root", 0, 0, page, meta, ROOTS)
def request(): return BatchRequest(str(RUN), "g", "c", "i", 0, (occ(),))

def test_identity_is_stable_and_checkpoint_is_runtime_validated():
    one = request(); assert one.batch_id == request().batch_id
    assert BatchCheckpoint(one).state is BatchState.PENDING
    with pytest.raises((TypeError, ValueError)): BatchRequest(str(RUN), "g", "c", "i", 0, (object(),))
    with pytest.raises(ValueError): BatchMetrics(-1, 0, 1, 0, 0)

def test_committed_checkpoint_requires_digest_and_metrics():
    with pytest.raises(ValueError): BatchCheckpoint(request(), state=BatchState.COMMITTED)

def test_leased_checkpoint_requires_exact_lease_attempt():
    req = request()
    lease = BatchLease(req.batch_id, "token", 100.0, 1, req.batch_id)
    for forged_attempt in (0, 2, True):
        with pytest.raises((TypeError, ValueError)):
            BatchCheckpoint(req, state=BatchState.LEASED, lease=lease, attempt=forged_attempt)
    for forged_lease_attempt in (2,):
        forged_lease = BatchLease(req.batch_id, "token", 100.0, forged_lease_attempt, req.batch_id)
        with pytest.raises(ValueError):
            BatchCheckpoint(req, state=BatchState.LEASED, lease=forged_lease, attempt=1)
    for invalid_lease_attempt in (0, True):
        with pytest.raises(ValueError):
            BatchLease(req.batch_id, "token", 100.0, invalid_lease_attempt, req.batch_id)
