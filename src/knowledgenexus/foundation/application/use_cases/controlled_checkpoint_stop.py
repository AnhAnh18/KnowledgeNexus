"""Pure session-level policy for pausing after durable inventory windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CommittedCheckpointTransition,
    IncludeRootProgress,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
)


@dataclass(frozen=True)
class ControlledStopPolicy:
    """Maximum number of newly committed inventory windows in one session."""

    max_inventory_window_commits: int | None = None

    def __post_init__(self) -> None:
        value = self.max_inventory_window_commits
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("max_inventory_window_commits must be a positive int or None")


def is_inventory_window_commit(transition: CommittedCheckpointTransition) -> bool:
    """Classify descendant-window transitions without inspecting infrastructure state."""

    if type(transition) is not CommittedCheckpointTransition:
        raise TypeError("transition must be CommittedCheckpointTransition")
    return (
        transition.from_progress is IncludeRootProgress.DESCENDANTS_PENDING
        and transition.to_progress
        in {
            IncludeRootProgress.DESCENDANTS_PENDING,
            IncludeRootProgress.DESCENDANTS_COMPLETE,
        }
    )


@dataclass(frozen=True, repr=False)
class ControlledStopDecision:
    status: Literal["continue", "pause"]
    committed_count: int
    threshold: int | None
    reason: Literal["controlled_checkpoint_stop"] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"continue", "pause"}:
            raise ValueError("invalid controlled stop status")
        if type(self.committed_count) is not int or self.committed_count < 0:
            raise ValueError("invalid controlled stop count")
        if self.threshold is not None and (
            type(self.threshold) is not int or self.threshold <= 0
        ):
            raise ValueError("invalid controlled stop threshold")
        if self.status == "pause" and self.reason != "controlled_checkpoint_stop":
            raise ValueError("invalid controlled stop reason")
        if self.status == "pause" and (
            self.threshold is None or self.committed_count < self.threshold
        ):
            raise ValueError("invalid controlled stop decision")
        if self.status == "continue" and self.reason is not None:
            raise ValueError("invalid controlled stop reason")

    def __repr__(self) -> str:
        return (
            f"ControlledStopDecision(status={self.status!r}, "
            f"committed_count={self.committed_count}, threshold={self.threshold!r})"
        )


class ControlledStopController:
    """Count durable window events and decide whether the session should pause."""

    def __init__(self, policy: ControlledStopPolicy) -> None:
        if type(policy) is not ControlledStopPolicy:
            raise TypeError("policy must be ControlledStopPolicy")
        self._policy = policy
        self._committed_count = 0

    @property
    def committed_count(self) -> int:
        return self._committed_count

    @property
    def threshold(self) -> int | None:
        return self._policy.max_inventory_window_commits

    def record(self, result: CheckpointCommitResult) -> ControlledStopDecision:
        if type(result) is not CheckpointCommitResult:
            raise TypeError("result must be CheckpointCommitResult")
        if not result.replayed and is_inventory_window_commit(result.transition):
            self._committed_count += 1
        paused = (
            self.threshold is not None and self._committed_count >= self.threshold
        )
        return ControlledStopDecision(
            "pause" if paused else "continue",
            self._committed_count,
            self.threshold,
            "controlled_checkpoint_stop" if paused else None,
        )


__all__ = [
    "ControlledStopController",
    "ControlledStopDecision",
    "ControlledStopPolicy",
    "is_inventory_window_commit",
]
