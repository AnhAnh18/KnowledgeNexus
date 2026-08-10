from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_batch import BatchFailureCategory, BatchMetrics, BatchState, BatchRequest
from knowledgenexus.foundation.domain.models import CrawlRunId, CanonicalIncludeRoots, ConfluencePageMetadata, InventoryOccurrence
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_confluence_crawl_batch_store import SQLiteConfluenceCrawlBatchStore
from knowledgenexus.foundation.ports.confluence_crawl_batch_port import BatchLeaseConflict
from tests.foundation.domain.models.test_confluence_crawl_batch import request, RUN, ROOTS


def _two_page_request() -> BatchRequest:
    occurrences = []
    for ordinal, page_id in enumerate(("page", "page-2")):
        metadata = ConfluencePageMetadata(
            page_id,
            "Page " + str(ordinal),
            "S",
            parent_page_id="root",
            ancestor_page_ids=("root",),
            ancestor_titles=("Root",),
        )
        occurrences.append(InventoryOccurrence(RUN, 0, "root", 0, ordinal, page_id, metadata, ROOTS))
    return BatchRequest(str(RUN), "g", "c", "i", 0, tuple(occurrences))


def _tamper_occurrence(tmp_path: Path, mutate) -> None:
    import json
    import sqlite3

    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    with sqlite3.connect(tmp_path / "batch_state.sqlite3") as conn:
        row = conn.execute("SELECT occurrence_json FROM batch_requests WHERE ordinal=0").fetchone()
        payload = json.loads(row[0])
        mutate(payload[0])
        conn.execute("UPDATE batch_requests SET occurrence_json=? WHERE ordinal=0", (json.dumps(payload, separators=(",", ":"), sort_keys=True),))
        conn.commit()
    with pytest.raises((ValueError, KeyError)):
        SQLiteConfluenceCrawlBatchStore(tmp_path).get(req.batch_id)


def test_sidecar_create_claim_commit_and_reopen(tmp_path: Path) -> None:
    req = request()
    store = SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    lease = store.claim(req.batch_id, token="worker-1", now=10.0, lease_seconds=5.0)
    committed = store.commit(lease, batch_digest="a" * 64, metrics=BatchMetrics(1, 2, 1, 0, 0.1), now=11.0)
    assert committed.state is BatchState.COMMITTED
    reopened = SQLiteConfluenceCrawlBatchStore(tmp_path, requests=[req])
    assert reopened.get(req.batch_id) == committed


def test_sidecar_expired_lease_fences_stale_worker(tmp_path: Path) -> None:
    req = request()
    store = SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    old = store.claim(req.batch_id, token="old", now=1.0, lease_seconds=1.0)
    new = store.claim(req.batch_id, token="new", now=3.0, lease_seconds=1.0)
    with pytest.raises(Exception):
        store.commit(old, batch_digest="b" * 64, metrics=BatchMetrics(1, 2, 1, 0, 0), now=3.1)
    assert new.attempt == 2


def test_sidecar_rejects_schema_tampering(tmp_path: Path) -> None:
    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    import sqlite3
    with sqlite3.connect(tmp_path / "batch_state.sqlite3") as conn:
        conn.execute("DROP INDEX idx_batch_pending")
        conn.commit()
    with pytest.raises(ValueError):
        SQLiteConfluenceCrawlBatchStore(tmp_path, requests=[req]).get(req.batch_id)


def test_sidecar_reopen_reconstructs_request_without_catalog(tmp_path: Path) -> None:
    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    reopened = SQLiteConfluenceCrawlBatchStore(tmp_path)
    assert reopened.get(req.batch_id).request == req


def test_sidecar_requeue_enforces_retry_policy_and_clears_failure(tmp_path: Path) -> None:
    req = request()
    store = SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    lease = store.claim(req.batch_id, token="retry", now=1.0, lease_seconds=10.0)
    pending = store.requeue(lease, category=BatchFailureCategory.TRANSPORT, now=2.0)
    assert pending.state is BatchState.PENDING and pending.failure_category is None
    lease = store.claim(req.batch_id, token="terminal", now=3.0, lease_seconds=10.0)
    failed = store.requeue(lease, category=BatchFailureCategory.POLICY, now=4.0)
    assert failed.state is BatchState.FAILED and failed.failure_category is BatchFailureCategory.POLICY


def test_sidecar_rejects_existing_non_sidecar_database_without_mutation(tmp_path: Path) -> None:
    import sqlite3
    path = tmp_path / "batch_state.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE legacy(value TEXT)")
        conn.commit()
    with pytest.raises(ValueError):
        SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [request()])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("legacy",)]


def test_sidecar_rejects_binding_tamper(tmp_path: Path) -> None:
    import sqlite3
    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    with sqlite3.connect(tmp_path / "batch_state.sqlite3") as conn:
        conn.execute("UPDATE batch_runs SET workspace='other' WHERE singleton=1")
        conn.commit()
    with pytest.raises(ValueError):
        SQLiteConfluenceCrawlBatchStore(tmp_path).get(req.batch_id)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["metadata"].__setitem__("title", "tampered"),
        lambda value: value["metadata"].__setitem__("page_id", "other-page"),
        lambda value: value.__setitem__("run_id", "423e4567-e89b-42d3-a456-426614174000"),
        lambda value: value.__setitem__("include_root_page_id", "other-root"),
        lambda value: value.__setitem__("window_start", 1),
        lambda value: value["metadata"].__setitem__("labels", ["tampered"]),
        lambda value: value["metadata"].__setitem__("ancestor_page_ids", ["other-root"]),
    ],
)
def test_sidecar_rejects_any_occurrence_field_tamper(tmp_path: Path, mutate) -> None:
    _tamper_occurrence(tmp_path, mutate)


def test_occurrence_stream_digest_is_canonical_and_order_bound(tmp_path: Path) -> None:
    req = _two_page_request()
    first = SQLiteConfluenceCrawlBatchStore._occurrence_stream_digest((req,))
    second = SQLiteConfluenceCrawlBatchStore._occurrence_stream_digest((req,))
    assert first == second and len(first) == 64
    reordered = BatchRequest(req.run_id, req.generation_digest, req.config_digest, req.inventory_digest, 0, tuple(reversed(req.occurrences)))
    assert SQLiteConfluenceCrawlBatchStore._occurrence_stream_digest((reordered,)) != first


def test_sidecar_rejects_reordered_duplicate_or_gapped_persisted_stream(tmp_path: Path) -> None:
    import sqlite3

    req = _two_page_request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    with sqlite3.connect(tmp_path / "batch_state.sqlite3") as conn:
        conn.execute("UPDATE batch_pages SET occurrence_ordinal=2 WHERE occurrence_ordinal=1")
        conn.commit()
    with pytest.raises(ValueError):
        SQLiteConfluenceCrawlBatchStore(tmp_path).list_next_pending(1)


def test_sidecar_rejects_malformed_or_extra_occurrence_fields(tmp_path: Path) -> None:
    _tamper_occurrence(tmp_path, lambda value: value.__setitem__("unexpected", True))


def test_sidecar_rejects_supplied_request_metadata_drift(tmp_path: Path) -> None:
    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    metadata = ConfluencePageMetadata("page", "different", "S", parent_page_id="root", ancestor_page_ids=("root",), ancestor_titles=("Root",))
    drifted_occurrence = InventoryOccurrence(RUN, 0, "root", 0, 0, "page", metadata, ROOTS)
    drifted = BatchRequest(req.run_id, req.generation_digest, req.config_digest, req.inventory_digest, req.ordinal, (drifted_occurrence,))
    with pytest.raises(BatchLeaseConflict) as error:
        SQLiteConfluenceCrawlBatchStore(tmp_path, requests=[drifted]).get(req.batch_id)
    assert "identity" in str(error.value)


def test_sidecar_rejects_erased_request_stream_after_binding_without_mutation(tmp_path: Path) -> None:
    import sqlite3

    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    path = tmp_path / "batch_state.sqlite3"
    with sqlite3.connect(path) as conn:
        before_checkpoints = conn.execute("SELECT * FROM batch_checkpoints").fetchall()
        before_failures = conn.execute("SELECT * FROM batch_attempt_failures").fetchall()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM batch_pages")
        conn.execute("DELETE FROM batch_requests")
        conn.commit()
        assert conn.execute("SELECT * FROM batch_checkpoints").fetchall() == before_checkpoints
        assert conn.execute("SELECT * FROM batch_attempt_failures").fetchall() == before_failures
    store = SQLiteConfluenceCrawlBatchStore(tmp_path)
    for operation in (
        lambda: store.get(req.batch_id),
        lambda: store.list_next_pending(1),
        lambda: store.claim(req.batch_id, token="worker", now=1.0, lease_seconds=5.0),
    ):
        with pytest.raises(ValueError):
            operation()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM batch_checkpoints").fetchall() == before_checkpoints
        assert conn.execute("SELECT * FROM batch_attempt_failures").fetchall() == before_failures


@pytest.mark.parametrize(
    "state, sql, params",
    [
        ("pending metric", "UPDATE batch_checkpoints SET byte_count=1 WHERE batch_id=?", ()),
        ("pending attempt", "UPDATE batch_checkpoints SET attempt=1 WHERE batch_id=?", ()),
        ("leased token", "UPDATE batch_checkpoints SET state='leased',attempt=1,token='',expires_at=2 WHERE batch_id=?", ()),
        ("leased expiry", "UPDATE batch_checkpoints SET state='leased',attempt=1,token='worker',expires_at='bad' WHERE batch_id=?", ()),
        ("failed attempt", "UPDATE batch_checkpoints SET state='failed',attempt=0,failure_category='policy' WHERE batch_id=?", ()),
        ("failed metric", "UPDATE batch_checkpoints SET state='failed',attempt=1,failure_category='policy',byte_count=1 WHERE batch_id=?", ()),
        ("committed digest", "UPDATE batch_checkpoints SET state='committed',attempt=1,batch_digest='BAD',page_count=1,byte_count=0,request_count=1,retry_count=0,elapsed_seconds=0,queue_high_watermark=0 WHERE batch_id=?", ()),
        ("committed count", "UPDATE batch_checkpoints SET state='committed',attempt=1,batch_digest=?,page_count=99,byte_count=0,request_count=99,retry_count=0,elapsed_seconds=0,queue_high_watermark=0 WHERE batch_id=?", ("a" * 64,)),
        ("committed NaN", "UPDATE batch_checkpoints SET state='committed',attempt=1,batch_digest=?,page_count=1,byte_count=-1,request_count=1,retry_count=0,elapsed_seconds='nan',queue_high_watermark=0 WHERE batch_id=?", ("a" * 64,)),
    ],
)
def test_sidecar_rejects_impossible_persisted_checkpoint_rows(tmp_path: Path, state: str, sql: str, params: tuple) -> None:
    import sqlite3

    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    path = tmp_path / "batch_state.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(sql, (*params, req.batch_id))
        conn.commit()
        before = conn.execute("SELECT * FROM batch_checkpoints").fetchall()
    with pytest.raises(ValueError):
        SQLiteConfluenceCrawlBatchStore(tmp_path).get(req.batch_id)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM batch_checkpoints").fetchall() == before


def test_sidecar_expired_reclaim_is_fenced_at_max_attempts(tmp_path: Path) -> None:
    req = request()
    SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    store = SQLiteConfluenceCrawlBatchStore(tmp_path, max_attempts=2)
    first = store.claim(req.batch_id, token="worker-1", now=1.0, lease_seconds=1.0)
    second = store.claim(req.batch_id, token="worker-2", now=3.0, lease_seconds=1.0)
    assert first.attempt == 1 and second.attempt == 2
    with pytest.raises(BatchLeaseConflict, match="max_attempts_exceeded"):
        store.claim(req.batch_id, token="worker-3", now=5.0, lease_seconds=1.0)
    terminal = store.get(req.batch_id)
    assert terminal.state is BatchState.FAILED
    assert terminal.attempt == 2
    assert terminal.failure_category is BatchFailureCategory.TIMEOUT
    with pytest.raises(BatchLeaseConflict):
        store.claim(req.batch_id, token="worker-4", now=6.0, lease_seconds=1.0)


def _forged_metrics(**changes: object) -> BatchMetrics:
    values = {
        "page_count": 1,
        "byte_count": 2,
        "request_count": 1,
        "retry_count": 0,
        "elapsed_seconds": 0.1,
        "queue_high_watermark": 0,
        "peak_rss_bytes": None,
    }
    values.update(changes)
    result = object.__new__(BatchMetrics)
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result


@pytest.mark.parametrize(
    "changes",
    [
        {"queue_high_watermark": 2},
        {"retry_count": 1},
        {"byte_count": -1},
        {"page_count": 2},
        {"request_count": 2},
        {"elapsed_seconds": float("nan")},
        {"peak_rss_bytes": -1},
    ],
)
def test_sidecar_rejects_invalid_commit_metrics_before_mutation(tmp_path: Path, changes: dict[str, object]) -> None:
    import sqlite3

    req = request()
    store = SQLiteConfluenceCrawlBatchStore.initialize(tmp_path, [req])
    lease = store.claim(req.batch_id, token="worker", now=1.0, lease_seconds=10.0)
    path = tmp_path / "batch_state.sqlite3"
    with sqlite3.connect(path) as conn:
        before_checkpoint = conn.execute("SELECT * FROM batch_checkpoints").fetchall()
        before_failures = conn.execute("SELECT * FROM batch_attempt_failures").fetchall()
    with pytest.raises((ValueError, TypeError)):
        store.commit(lease, batch_digest="a" * 64, metrics=_forged_metrics(**changes), now=2.0)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM batch_checkpoints").fetchall() == before_checkpoint
        assert conn.execute("SELECT * FROM batch_attempt_failures").fetchall() == before_failures
    assert store.get(req.batch_id).state is BatchState.LEASED
