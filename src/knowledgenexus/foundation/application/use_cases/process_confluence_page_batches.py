from __future__ import annotations
import hashlib
import math
import time
from dataclasses import dataclass
from typing import Callable, Iterable
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import *
from knowledgenexus.foundation.domain.rules.confluence_batch_retry_policy import is_retryable, backoff_seconds
from knowledgenexus.foundation.ports.confluence_crawl_batch_port import ConfluenceCrawlBatchPort, BatchLeaseConflict
from knowledgenexus.foundation.ports.confluence_page_fetch_port import ConfluencePageFetchPort

@dataclass(frozen=True)
class BatchRunConfig:
    batch_size: int = 100
    max_attempts: int = 3
    lease_seconds: float = 300.0
    queue_capacity: int = 1
    max_pages: int | None = None
    max_bytes: int | None = None
    max_requests: int | None = None
    max_page_bytes: int | None = None
    sleep: Callable[[float], None] = time.sleep
    def __post_init__(self) -> None:
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 1000: raise ValueError("batch_size is invalid")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100: raise ValueError("max_attempts is invalid")
        if type(self.lease_seconds) not in (int,float) or isinstance(self.lease_seconds, bool) or not math.isfinite(self.lease_seconds) or self.lease_seconds <= 0: raise ValueError("lease_seconds is invalid")
        if type(self.queue_capacity) is not int or not 1 <= self.queue_capacity <= 1000: raise ValueError("queue_capacity is invalid")
        for value in (self.max_pages, self.max_bytes, self.max_requests, self.max_page_bytes):
            if value is not None and (type(value) is not int or isinstance(value, bool) or value < 0): raise ValueError("budget is invalid")
        if not callable(self.sleep): raise TypeError("sleep is invalid")

@dataclass(frozen=True)
class BatchRunResult:
    committed: int
    failed: int
    retries: int
    page_count: int
    byte_count: int
    queue_high_watermark: int
    digest: str
    total_batches: int = 0
    total_requests: int = 0
    total_pages: int = 0
    total_bytes: int = 0
    total_retries: int = 0
    def __post_init__(self) -> None:
        for value in (self.committed, self.failed, self.retries, self.page_count, self.byte_count, self.queue_high_watermark):
            if type(value) is not int or isinstance(value, bool) or value < 0: raise ValueError("result counter is invalid")
        if type(self.digest) is not str or len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest): raise ValueError("result digest is invalid")
        if type(self.total_batches) is not int or self.total_batches < 0: raise ValueError("total_batches is invalid")
        if self.committed + self.failed != self.total_batches: raise ValueError("result batch count is incoherent")
        if self.queue_high_watermark > 1: raise ValueError("queue watermark is unbounded")
        for value in (self.total_requests, self.total_pages, self.total_bytes, self.total_retries):
            if type(value) is not int or value < 0: raise ValueError("total accounting is invalid")
        if self.total_requests != self.total_pages or self.total_pages != self.page_count or self.total_bytes != self.byte_count or self.total_retries != self.retries: raise ValueError("total accounting mismatch")
        expected = hashlib.sha256(f"{self.committed}:{self.failed}:{self.total_requests}:{self.total_pages}:{self.total_bytes}:{self.total_retries}:{self.queue_high_watermark}".encode()).hexdigest()
        if self.digest != expected: raise ValueError("result digest mismatch")

class ProcessConfluencePageBatches:
    """Synchronous bounded driver; transport and page-set processing are injected."""
    def __init__(self, *, store: ConfluenceCrawlBatchPort, fetcher: ConfluencePageFetchPort,
                 process_page_set: Callable[[tuple[tuple[str, bytes], ...]], object] | None = None,
                 clock: Callable[[], float] = time.monotonic, token_factory: Callable[[str], str] = lambda batch_id: hashlib.sha256(batch_id.encode()).hexdigest()):
        self._store = store; self._fetcher = fetcher; self._process = process_page_set or (lambda pages: None); self._clock = clock; self._token = token_factory

    @staticmethod
    def partition(*, run_id: str, generation_digest: str, config_digest: str, inventory_digest: str,
                  occurrences: Iterable, batch_size: int = 100) -> tuple[BatchRequest, ...]:
        if type(batch_size) is not int or not 1 <= batch_size <= 1000: raise ValueError("batch_size is invalid")
        values = tuple(occurrences)
        if any(type(x) is not type(values[0]) for x in values) if values else False: raise TypeError("occurrences are invalid")
        result = []
        for ordinal in range(0, len(values), batch_size):
            result.append(BatchRequest(run_id, generation_digest, config_digest, inventory_digest, ordinal // batch_size, values[ordinal:ordinal + batch_size]))
        return tuple(result)

    def run(self, requests: Iterable[BatchRequest], *, config: BatchRunConfig = BatchRunConfig()) -> BatchRunResult:
        reqs = tuple(requests)
        self._validate_requests(reqs, config)
        committed = failed = retries = pages = bytes_total = qmax = requests_total = 0
        # Physical transport usage includes failed attempts in this invocation.
        # It is deliberately invocation-scoped because the reference port does
        # not persist failed-attempt resource counters across process restarts.
        physical_requests = physical_bytes = 0
        for request in reqs:
            try:
                self._store.create(BatchCheckpoint(request))
            except BatchLeaseConflict:
                # Re-entry is the normal resume path for an already-created batch.
                existing = self._store.get(request.batch_id)
                if existing.request != request:
                    raise
            done = False
            while not done:
                current = self._store.get(request.batch_id)
                if current.state is BatchState.COMMITTED:
                    committed += 1; pages += current.metrics.page_count; bytes_total += current.metrics.byte_count; requests_total += current.metrics.request_count; retries += current.metrics.retry_count
                    physical_requests += current.metrics.request_count; physical_bytes += current.metrics.byte_count
                    done = True; continue
                if current.state is BatchState.FAILED:
                    # Failed checkpoints are terminal; re-entry reports the same
                    # batch outcome without claiming or invoking transport.
                    failed += 1
                    done = True
                    continue
                lease = self._store.claim(request.batch_id, token=self._token(request.batch_id), now=self._clock(), lease_seconds=config.lease_seconds)
                try:
                    payload = []
                    batch_bytes = 0
                    batch_retries = lease.attempt - 1
                    attempt_requests = 0
                    attempt_bytes = 0
                    for occurrence in request.occurrences:
                        if config.max_requests is not None and physical_requests + 1 > config.max_requests: raise ValueError("policy budget exceeded")
                        if config.max_pages is not None and pages + len(payload) >= config.max_pages: raise ValueError("policy budget exceeded")
                        if hasattr(self._fetcher, "estimate_page_bytes"):
                            estimate = self._fetcher.estimate_page_bytes(page_id=occurrence.page_id)
                            if type(estimate) is not int or estimate < 0: raise ValueError("policy budget exceeded")
                            if config.max_page_bytes is not None and estimate > config.max_page_bytes: raise ValueError("policy budget exceeded")
                            if config.max_bytes is not None and physical_bytes + estimate > config.max_bytes: raise ValueError("policy budget exceeded")
                        attempt_requests += 1
                        physical_requests += 1
                        body = self._fetcher.fetch_page_raw(page_id=occurrence.page_id)
                        if type(body) is not bytes: raise TypeError("fetcher returned invalid body")
                        if config.max_page_bytes is not None and len(body) > config.max_page_bytes: raise ValueError("policy budget exceeded")
                        physical_bytes += len(body)
                        payload.append((occurrence.page_id, body)); attempt_bytes += len(body); batch_bytes += len(body)
                        if config.max_bytes is not None and physical_bytes > config.max_bytes: raise ValueError("policy budget exceeded")
                    digest = hashlib.sha256(b"".join(body for _, body in payload)).hexdigest()
                    page_bytes = sum(len(b) for _, b in payload)
                    if config.max_pages is not None and pages + len(payload) > config.max_pages or config.max_bytes is not None and physical_bytes > config.max_bytes:
                        raise ValueError("policy budget exceeded")
                    self._process(tuple(payload))
                    self._store.commit(lease, batch_digest=digest, metrics=BatchMetrics(len(payload), page_bytes, len(payload), batch_retries, 0.0, 1), now=self._clock())
                    committed += 1; pages += len(payload); bytes_total += attempt_bytes; requests_total += attempt_requests; retries += batch_retries; done = True
                except Exception as error:
                    category = BatchFailureCategory.MALFORMED if isinstance(error, (TypeError, ValueError)) else BatchFailureCategory.TRANSPORT
                    try:
                        if is_retryable(category) and lease.attempt < config.max_attempts:
                            self._store.requeue(lease, category=category, now=self._clock())
                            config.sleep(backoff_seconds(attempt=lease.attempt))
                        else:
                            self._store.fail(lease, category=category, now=self._clock())
                    except BatchLeaseConflict: pass
                    if not is_retryable(category) or lease.attempt >= config.max_attempts:
                        failed += 1; done = True
                    else: pass
        qmax = 1 if reqs else 0
        digest = hashlib.sha256(f"{committed}:{failed}:{requests_total}:{pages}:{bytes_total}:{retries}:{qmax}".encode()).hexdigest()
        return BatchRunResult(committed, failed, retries, pages, bytes_total, qmax, digest, len(reqs), requests_total, pages, bytes_total, retries)

    @staticmethod
    def _validate_requests(reqs: tuple[BatchRequest, ...], config: BatchRunConfig) -> None:
        if any(type(x) is not BatchRequest for x in reqs): raise TypeError("requests are invalid")
        if [x.ordinal for x in reqs] != list(range(len(reqs))): raise ValueError("batch ordinals are not contiguous")
        if len({x.batch_id for x in reqs}) != len(reqs): raise ValueError("duplicate batch identity")
        if reqs:
            identity = (reqs[0].run_id, reqs[0].generation_digest, reqs[0].config_digest, reqs[0].inventory_digest)
            if any((x.run_id, x.generation_digest, x.config_digest, x.inventory_digest) != identity for x in reqs): raise ValueError("request identity drift")
            pages = [page.page_id for x in reqs for page in x.occurrences]
            if len(set(pages)) != len(pages): raise ValueError("duplicate page identity")
            ordinals = [page.item_ordinal for x in reqs for page in x.occurrences]
            if ordinals != list(range(len(ordinals))): raise ValueError("occurrence order drift")
