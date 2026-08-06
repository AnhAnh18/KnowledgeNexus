from __future__ import annotations
from dataclasses import replace
import math
from threading import Lock
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import *
from knowledgenexus.foundation.ports.confluence_crawl_batch_port import BatchLeaseConflict

class InMemoryConfluenceCrawlBatchStore:
    """Deterministic reference store used by bounded/synthetic orchestration tests."""
    def __init__(self) -> None:
        self._lock = Lock(); self._items: dict[str, BatchCheckpoint] = {}
    def create(self, checkpoint: BatchCheckpoint) -> BatchCheckpoint:
        if type(checkpoint) is not BatchCheckpoint: raise TypeError("checkpoint is invalid")
        with self._lock:
            old = self._items.get(checkpoint.request.batch_id)
            if old is not None and old != checkpoint: raise BatchLeaseConflict("identity_conflict")
            self._items[checkpoint.request.batch_id] = checkpoint
            return checkpoint
    def get(self, batch_id: str) -> BatchCheckpoint:
        if type(batch_id) is not str or not batch_id: raise ValueError("batch_id is invalid")
        with self._lock: return self._items[batch_id]
    def claim(self, batch_id: str, *, token: str, now: float, lease_seconds: float) -> BatchLease:
        if type(batch_id) is not str or not batch_id: raise ValueError("batch_id is invalid")
        if type(token) is not str or not token or type(now) not in (int,float) or isinstance(now, bool) or type(lease_seconds) not in (int,float) or isinstance(lease_seconds, bool) or lease_seconds <= 0: raise ValueError("lease request is invalid")
        with self._lock:
            current = self._items[batch_id]
            if current.state in (BatchState.COMMITTED, BatchState.FAILED) or (current.state is BatchState.LEASED and current.lease and current.lease.expires_at > now): raise BatchLeaseConflict("already_leased")
            if current.state is BatchState.LEASED and current.lease is not None and token == current.lease.token: raise BatchLeaseConflict("reclaim_token_reuse")
            lease = BatchLease(batch_id, token, now + lease_seconds, current.attempt + 1, batch_id)
            self._items[batch_id] = replace(current, state=BatchState.LEASED, lease=lease, attempt=lease.attempt, failure_category=None)
            return lease
    def renew(self, lease: BatchLease, *, now: float, lease_seconds: float) -> BatchLease:
        if type(lease) is not BatchLease: raise TypeError("lease is invalid")
        with self._lock:
            current = self._items[lease.batch_id]
            if type(now) not in (int,float) or isinstance(now, bool) or type(lease_seconds) not in (int,float) or isinstance(lease_seconds, bool) or lease_seconds <= 0: raise ValueError("renew input is invalid")
            if current.state is not BatchState.LEASED or current.lease != lease or lease.expires_at <= now: raise BatchLeaseConflict("stale_lease")
            renewed = replace(lease, expires_at=now + lease_seconds)
            self._items[lease.batch_id] = replace(current, lease=renewed)
            return renewed
    def commit(self, lease: BatchLease, *, batch_digest: str, metrics: BatchMetrics, now: float) -> BatchCheckpoint:
        if type(lease) is not BatchLease or type(metrics) is not BatchMetrics: raise TypeError("commit input is invalid")
        if type(batch_digest) is not str or len(batch_digest) != 64 or any(c not in "0123456789abcdef" for c in batch_digest): raise ValueError("digest is invalid")
        with self._lock:
            current = self._items[lease.batch_id]
            if current.state is BatchState.COMMITTED:
                if current.batch_digest != batch_digest or current.metrics != metrics: raise BatchLeaseConflict("digest_conflict")
                return current
            if type(now) not in (int,float) or isinstance(now, bool) or lease.expires_at <= now: raise BatchLeaseConflict("stale_lease")
            if current.state is not BatchState.LEASED or current.lease != lease or metrics.page_count != len(current.request.occurrences): raise BatchLeaseConflict("stale_lease")
            committed = replace(current, state=BatchState.COMMITTED, lease=None, batch_digest=batch_digest, metrics=metrics)
            self._items[lease.batch_id] = committed; return committed
    def fail(self, lease: BatchLease, *, category: BatchFailureCategory, now: float) -> BatchCheckpoint:
        if type(lease) is not BatchLease: raise TypeError("lease is invalid")
        if not isinstance(category, BatchFailureCategory): raise TypeError("category is invalid")
        if type(now) not in (int, float) or isinstance(now, bool) or not math.isfinite(now): raise ValueError("now is invalid")
        with self._lock:
            current = self._items[lease.batch_id]
            if current.state is not BatchState.LEASED or current.lease != lease or lease.expires_at <= now: raise BatchLeaseConflict("stale_lease")
            failed = replace(current, state=BatchState.FAILED, lease=None, failure_category=category)
            self._items[lease.batch_id] = failed; return failed
    def requeue(self, lease: BatchLease, *, category: BatchFailureCategory, now: float) -> BatchCheckpoint:
        if type(lease) is not BatchLease or not isinstance(category, BatchFailureCategory): raise TypeError("requeue input is invalid")
        if type(now) not in (int, float) or isinstance(now, bool) or not math.isfinite(now): raise ValueError("now is invalid")
        with self._lock:
            current = self._items[lease.batch_id]
            if current.state is not BatchState.LEASED or current.lease != lease or lease.expires_at <= now: raise BatchLeaseConflict("stale_lease")
            pending = replace(current, state=BatchState.PENDING, lease=None, failure_category=None)
            self._items[lease.batch_id] = pending; return pending
