"""Port for a pinned, read-only local Git repository snapshot."""

from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.git_code_source import (
    GitCodeBuildError,
    GitRepositorySnapshot,
    GitSourceConfig,
)


class GitRepositoryReadPort(Protocol):
    def read(self, *, config: GitSourceConfig) -> GitRepositorySnapshot:
        """Read one exact commit without exposing partial output."""


class GitRepositoryReaderError(GitCodeBuildError):
    """Compatibility error type for infrastructure adapters."""
