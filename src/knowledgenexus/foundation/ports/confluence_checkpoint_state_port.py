from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CheckpointFailureCategory(StrEnum):
    CHECKPOINT_FAILURE = "checkpoint_failure"


class CheckpointStateError(Exception):
    """Sanitized, stable checkpoint-state failure."""

    category = CheckpointFailureCategory.CHECKPOINT_FAILURE

    def __init__(self) -> None:
        super().__init__(self.category.value)

    def __repr__(self) -> str:
        return "CheckpointStateError('checkpoint_failure')"


@dataclass(frozen=True)
class CheckpointSchemaState:
    schema_version: int

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version < 0:
            raise CheckpointStateError() from None


class ConfluenceCheckpointStatePort(Protocol):
    """Safe schema seam; later stages use C1-B facts, never untyped dicts.

    Future operations accept and return `CrawlRunId`, `CrawlRunSnapshot`,
    `InventoryRootCommit`, and `InventoryWindowCommit` directly.
    """

    def read_schema_state(self) -> CheckpointSchemaState: ...
