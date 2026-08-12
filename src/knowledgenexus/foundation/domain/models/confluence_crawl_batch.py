from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import InventoryOccurrence


class BatchState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMMITTED = "committed"
    FAILED = "failed"


class BatchFailureCategory(StrEnum):
    RATE_LIMIT = "rate_limit"
    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    LOCAL_TRANSIENT = "local_transient"
    MALFORMED = "malformed"
    POLICY = "policy"
    SCHEMA = "schema"
    STALE_GENERATION = "stale_generation"
    IDENTITY = "identity"


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} is invalid")
    return value


def batch_identity(*, run_id: str, generation_digest: str, config_digest: str,
                   inventory_digest: str, ordinal: int, occurrences: Iterable[InventoryOccurrence]) -> str:
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("ordinal is invalid")
    items = tuple(occurrences)
    if not items or any(type(item) is not InventoryOccurrence for item in items):
        raise ValueError("occurrences are invalid")
    ids = tuple(item.page_id for item in items)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate page identity")
    payload = {"run": _text(run_id, "run_id"), "generation": _text(generation_digest, "generation_digest"),
               "config": _text(config_digest, "config_digest"), "inventory": _text(inventory_digest, "inventory_digest"),
               "ordinal": ordinal, "pages": ids}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class BatchRequest:
    run_id: str
    generation_digest: str
    config_digest: str
    inventory_digest: str
    ordinal: int
    occurrences: tuple[InventoryOccurrence, ...]

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id"); _text(self.generation_digest, "generation_digest")
        _text(self.config_digest, "config_digest"); _text(self.inventory_digest, "inventory_digest")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal is invalid")
        if type(self.occurrences) is not tuple or not self.occurrences:
            raise ValueError("occurrences are invalid")
        if any(type(x) is not InventoryOccurrence for x in self.occurrences):
            raise TypeError("occurrences are invalid")
        if len({x.page_id for x in self.occurrences}) != len(self.occurrences):
            raise ValueError("duplicate page identity")

    @property
    def batch_id(self) -> str:
        return batch_identity(run_id=self.run_id, generation_digest=self.generation_digest,
                              config_digest=self.config_digest, inventory_digest=self.inventory_digest,
                              ordinal=self.ordinal, occurrences=self.occurrences)


@dataclass(frozen=True)
class BatchLease:
    batch_id: str
    token: str
    expires_at: float
    attempt: int
    request_batch_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.batch_id, "batch_id"); _text(self.token, "token")
        if self.request_batch_id is not None and self.request_batch_id != self.batch_id: raise ValueError("lease/request identity mismatch")
        if type(self.expires_at) not in (int, float) or isinstance(self.expires_at, bool) or not math.isfinite(self.expires_at) or self.expires_at < 0 or type(self.attempt) is not int or self.attempt <= 0:
            raise ValueError("lease is invalid")


@dataclass(frozen=True)
class BatchMetrics:
    page_count: int
    byte_count: int
    request_count: int
    retry_count: int
    elapsed_seconds: float
    queue_high_watermark: int = 0
    peak_rss_bytes: int | None = None

    def __post_init__(self) -> None:
        for value in (self.page_count, self.byte_count, self.request_count, self.retry_count, self.queue_high_watermark):
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise ValueError("metrics counter is invalid")
        if type(self.elapsed_seconds) not in (int, float) or isinstance(self.elapsed_seconds, bool) or not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds is invalid")
        if self.peak_rss_bytes is not None and (type(self.peak_rss_bytes) is not int or isinstance(self.peak_rss_bytes, bool) or self.peak_rss_bytes < 0):
            raise ValueError("peak_rss_bytes is invalid")
        if self.request_count < self.page_count: raise ValueError("request/page count is incoherent")


@dataclass(frozen=True)
class BatchCheckpoint:
    request: BatchRequest
    state: BatchState = BatchState.PENDING
    lease: BatchLease | None = None
    attempt: int = 0
    failure_category: BatchFailureCategory | None = None
    batch_digest: str | None = None
    metrics: BatchMetrics | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not BatchRequest or not isinstance(self.state, BatchState):
            raise TypeError("checkpoint is invalid")
        if type(self.attempt) is not int or isinstance(self.attempt, bool) or self.attempt < 0:
            raise ValueError("attempt is invalid")
        if self.state is BatchState.LEASED and type(self.lease) is not BatchLease:
            raise ValueError("leased checkpoint requires lease")
        if self.state is BatchState.LEASED and (self.lease.batch_id != self.request.batch_id or self.lease.request_batch_id != self.request.batch_id):
            raise ValueError("leased checkpoint identity mismatch")
        if self.state is BatchState.LEASED and self.attempt != self.lease.attempt:
            raise ValueError("leased checkpoint attempt mismatch")
        if self.state is not BatchState.LEASED and self.lease is not None:
            raise ValueError("non-leased checkpoint cannot carry lease")
        if self.failure_category is not None and not isinstance(self.failure_category, BatchFailureCategory):
            raise TypeError("failure category is invalid")
        if self.state is BatchState.COMMITTED and (not self.batch_digest or self.metrics is None):
            raise ValueError("committed checkpoint is incomplete")
        if self.state is BatchState.COMMITTED and (type(self.batch_digest) is not str or len(self.batch_digest) != 64 or any(c not in "0123456789abcdef" for c in self.batch_digest)):
            raise ValueError("committed digest is invalid")
        if self.state is BatchState.COMMITTED and (self.metrics.page_count != len(self.request.occurrences) or self.metrics.request_count != self.metrics.page_count or self.metrics.queue_high_watermark > 1 or self.metrics.retry_count > self.attempt - 1):
            raise ValueError("committed metrics are incoherent")
        if self.state is BatchState.LEASED and (self.batch_digest is not None or self.metrics is not None or self.failure_category is not None):
            raise ValueError("leased checkpoint contains commit data")
        if self.state is BatchState.COMMITTED and self.attempt < 1:
            raise ValueError("committed checkpoint attempt is invalid")
        if self.state is BatchState.COMMITTED and self.failure_category is not None:
            raise ValueError("committed checkpoint cannot fail")
        if self.state is BatchState.FAILED and self.failure_category is None:
            raise ValueError("failed checkpoint requires failure category")
        if self.state is BatchState.FAILED and (self.batch_digest is not None or self.metrics is not None):
            raise ValueError("failed checkpoint cannot carry commit data")
        if self.state is BatchState.PENDING and (self.failure_category is not None or self.batch_digest is not None or self.metrics is not None):
            raise ValueError("pending checkpoint contains progress")
