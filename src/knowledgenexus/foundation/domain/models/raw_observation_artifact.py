from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, repr=False)
class RawObservationArtifact:
    """Metadata for one exact raw page-adjacent response artifact."""

    path: Path
    raw_sha256: str
    byte_count: int

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
