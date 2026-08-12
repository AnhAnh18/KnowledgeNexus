"""Finite publication guard around the approved immutable raw-page store."""
from __future__ import annotations

import os
import shutil
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, ContextManager, Iterator

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageArtifact,
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
    ConfluenceRawPageStoreFailureCategory,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
    ConfluenceRawPageStorePort,
)
from knowledgenexus.foundation.ports.path_safety import require_plain_directory_chain


def _fail() -> None:
    raise ConfluenceRawPageStoreError(
        ConfluenceRawPageStoreFailureCategory.RAW_PUBLICATION_FAILURE
    ) from None


class BudgetedConfluenceRawPageStore(ConfluenceRawPageStorePort):
    """Enforce generation byte and free-disk budgets before publication.

    The wrapped M7 store remains the authority for immutable paths, atomic
    publication, replay and evidence validation.  This guard only owns the W5
    resource boundary and is composed for live capture, never for readback.
    """

    def __init__(
        self,
        *,
        inner: ConfluenceRawPageStorePort,
        raw_root: Path,
        publication_guard: Callable[[], ContextManager[None]],
        max_total_bytes: int,
        minimum_free_disk_reserve_bytes: int,
        disk_usage: Callable[[str | os.PathLike[str]], object] = shutil.disk_usage,
    ) -> None:
        if any(
            not callable(getattr(inner, name, None))
            for name in ("resolve_page_path", "publish_page", "read_page")
        ):
            raise TypeError("inner raw-page store is invalid")
        if (
            not isinstance(raw_root, Path)
            or not raw_root.is_absolute()
            or not callable(publication_guard)
        ):
            raise ValueError("raw_root is invalid")
        try:
            require_plain_directory_chain(raw_root)
        except (OSError, TypeError, ValueError):
            raise ValueError("raw_root is invalid") from None
        if type(max_total_bytes) is not int or max_total_bytes <= 0:
            raise ValueError("max_total_bytes is invalid")
        if (
            type(minimum_free_disk_reserve_bytes) is not int
            or minimum_free_disk_reserve_bytes < 0
            or not callable(disk_usage)
        ):
            raise ValueError("disk budget is invalid")
        self._inner = inner
        self._raw_root = raw_root
        self._publication_guard = publication_guard
        self._max_total_bytes = max_total_bytes
        self._minimum_free_disk_reserve_bytes = minimum_free_disk_reserve_bytes
        self._disk_usage = disk_usage
        self._publication_lock = threading.Lock()

    def resolve_page_path(self, *, run_id: CrawlRunId, page_id: str) -> Path:
        return self._inner.resolve_page_path(run_id=run_id, page_id=page_id)

    def read_page(
        self, *, run_id: CrawlRunId, page_id: str
    ) -> ConfluenceRawPageEnvelope:
        return self._inner.read_page(run_id=run_id, page_id=page_id)

    def publish_page(
        self, *, envelope: ConfluenceRawPageEnvelope
    ) -> ConfluenceRawPageArtifact:
        if type(envelope) is not ConfluenceRawPageEnvelope:
            _fail()
        target = self.resolve_page_path(
            run_id=envelope.run_id, page_id=envelope.page_id
        )
        try:
            content_size = len(envelope.to_bytes())
        except Exception:
            _fail()
        # The injected guard is the already-held durable checkpoint writer
        # lease. It excludes every cooperating process for the entire raw
        # generation activation, so measure/check/publish and acknowledgement
        # share one authority instead of competing lock namespaces.
        with self._publication_lock, self._verified_publication_guard():
            # Existing evidence is replayed by the immutable inner store even
            # when the generation has reached its publication budget.
            if target.exists():
                return self._inner.publish_page(envelope=envelope)
            # Re-measure while holding the cross-process lease. A cached total
            # would become stale after publication by another store instance.
            current = self._measure_generation_bytes(envelope.run_id)
            if current + content_size > self._max_total_bytes:
                _fail()
            try:
                free = self._disk_usage(self._raw_root).free
            except (AttributeError, OSError, TypeError, ValueError):
                _fail()
            if type(free) is not int or free < 0:
                _fail()
            if free - content_size < self._minimum_free_disk_reserve_bytes:
                _fail()
            artifact = self._inner.publish_page(envelope=envelope)
            return artifact

    @contextmanager
    def _verified_publication_guard(self) -> Iterator[None]:
        try:
            with self._publication_guard():
                yield
        except ConfluenceRawPageStoreError:
            raise
        except Exception:
            _fail()

    def _measure_generation_bytes(self, run_id: CrawlRunId) -> int:
        pages = self._raw_root / "confluence" / "generations" / str(run_id) / "pages"
        if not pages.exists():
            return 0
        try:
            require_plain_directory_chain(pages)
            total = 0
            with os.scandir(pages) as entries:
                for entry in entries:
                    details = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or not stat.S_ISREG(details.st_mode):
                        _fail()
                    total += details.st_size
                    if total > self._max_total_bytes:
                        _fail()
            return total
        except ConfluenceRawPageStoreError:
            raise
        except (OSError, TypeError, ValueError, OverflowError):
            _fail()


__all__ = ["BudgetedConfluenceRawPageStore"]
