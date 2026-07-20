from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawPageArtifact:
    """Minimal metadata about one persisted raw page. Never carries content."""

    path: Path
    raw_sha256: str
    byte_count: int
