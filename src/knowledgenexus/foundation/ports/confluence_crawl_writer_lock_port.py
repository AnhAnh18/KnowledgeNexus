from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Protocol, Self


class ConfluenceCrawlWriterLockLease(Protocol):
    """Opaque lifecycle capability for one process-scoped writer lease."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class ConfluenceCrawlWriterLockPort(Protocol):
    """Typed acquisition seam; implementation details stay private."""

    def acquire(self, workspace: Path) -> ConfluenceCrawlWriterLockLease: ...


__all__ = [
    "ConfluenceCrawlWriterLockLease",
    "ConfluenceCrawlWriterLockPort",
]
