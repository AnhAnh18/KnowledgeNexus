from __future__ import annotations
from knowledgenexus.foundation.domain.models.confluence_crawl_batch import BatchFailureCategory

RETRYABLE = frozenset({BatchFailureCategory.RATE_LIMIT, BatchFailureCategory.TRANSPORT, BatchFailureCategory.TIMEOUT, BatchFailureCategory.LOCAL_TRANSIENT})

def is_retryable(category: BatchFailureCategory) -> bool:
    if not isinstance(category, BatchFailureCategory): raise TypeError("category is invalid")
    return category in RETRYABLE

def backoff_seconds(*, attempt: int, base_seconds: float = 1.0, max_seconds: float = 60.0) -> float:
    if type(attempt) is not int or attempt < 1 or type(base_seconds) not in (int,float) or base_seconds < 0 or type(max_seconds) not in (int,float) or max_seconds < 0:
        raise ValueError("backoff input is invalid")
    return min(float(max_seconds), float(base_seconds) * (2 ** (attempt - 1)))
