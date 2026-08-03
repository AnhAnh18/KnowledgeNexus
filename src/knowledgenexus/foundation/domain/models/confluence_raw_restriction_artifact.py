from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class ConfluenceRawRestrictionPublicationOutcome(StrEnum):
    PUBLISHED = "published"
    REUSED = "reused"


@dataclass(frozen=True, repr=False)
class ConfluenceRawRestrictionArtifact:
    """Metadata for one immutable generation-scoped restriction artifact."""

    path: Path
    run_id: CrawlRunId
    raw_sha256: str
    byte_count: int
    outcome: ConfluenceRawRestrictionPublicationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise TypeError("path expects an absolute pathlib.Path")
        if type(self.run_id) is not CrawlRunId:
            raise TypeError("run_id expects CrawlRunId")
        if not isinstance(self.raw_sha256, str) or _SHA256.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("byte_count is invalid")
        if not isinstance(
            self.outcome, ConfluenceRawRestrictionPublicationOutcome
        ):
            raise TypeError("outcome is invalid")

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(outcome={self.outcome.value!r}, byte_count={self.byte_count})"
        )


__all__ = [
    "ConfluenceRawRestrictionArtifact",
    "ConfluenceRawRestrictionPublicationOutcome",
]
