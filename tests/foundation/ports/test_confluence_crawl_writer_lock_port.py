from __future__ import annotations

import inspect

from knowledgenexus.foundation.ports import (
    ConfluenceCrawlWriterLockLease,
    ConfluenceCrawlWriterLockPort,
)


def test_writer_lock_port_exports_only_opaque_typed_lifecycle() -> None:
    assert ConfluenceCrawlWriterLockLease.__name__ == "ConfluenceCrawlWriterLockLease"
    assert ConfluenceCrawlWriterLockPort.__name__ == "ConfluenceCrawlWriterLockPort"
    lease_methods = {name for name in dir(ConfluenceCrawlWriterLockLease) if not name.startswith("_")}
    assert lease_methods == set()
    acquire = inspect.signature(ConfluenceCrawlWriterLockPort.acquire)
    assert tuple(acquire.parameters) == ("self", "workspace")
    assert not any(name in dir(ConfluenceCrawlWriterLockPort) for name in ("connection", "handle", "path", "mutate", "sql"))
