from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, Self

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CommittedCheckpointTransition,
    CrawlRunId,
    InventoryRootCommit,
    _validated_run_id,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
    InventoryWindowCommit,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionRequest,
)
from knowledgenexus.foundation.ports.confluence_raw_page_orphan_inspection_port import (
    ConfluenceRawPageOrphanInspectionPort,
)


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


class CheckpointOperationFailureCategory(StrEnum):
    """Stable categories returned by typed checkpoint mutations."""

    STATE_CONFLICT = "state_conflict"
    INVENTORY_IDENTITY_CONFLICT = "inventory_identity_conflict"
    INVENTORY_METADATA_CONFLICT = "inventory_metadata_conflict"
    PAGINATION_INVALID = "pagination_invalid"
    INVENTORY_PAGE_BUDGET_EXHAUSTED = "inventory_page_budget_exhausted"
    INVENTORY_WINDOW_LIMIT_EXHAUSTED = "inventory_window_limit_exhausted"
    REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"

    # Short aliases keep callers from having to duplicate the inventory scope
    # when a higher-level operation already supplies it.
    PAGE_BUDGET_EXHAUSTED = INVENTORY_PAGE_BUDGET_EXHAUSTED
    WINDOW_LIMIT_EXHAUSTED = INVENTORY_WINDOW_LIMIT_EXHAUSTED


class CheckpointOperationFailure(Exception):
    """Sanitized, typed failure for an operation-specific state mutation."""

    __slots__ = ("category",)

    def __init__(self, category: CheckpointOperationFailureCategory) -> None:
        if not isinstance(category, CheckpointOperationFailureCategory):
            raise TypeError("category expects CheckpointOperationFailureCategory")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        return f"CheckpointOperationFailure('{self.category.value}')"


class RawPageReplayDecision(StrEnum):
    COMMITTED = "committed"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
    MISSING = "missing"
    INVALID = "invalid"
    IDENTITY_CONFLICT = "identity_conflict"
    UNSAFE_TARGET = "unsafe_target"
    UNKNOWN_INVENTORY = "unknown_inventory"


class RawPageReplayFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INSPECTION_FAILED = "inspection_failed"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"


class RawPageReplayFailure(Exception):
    """Sanitized failure for the bounded raw-page replay operation."""

    def __init__(self, category: RawPageReplayFailureCategory) -> None:
        if not isinstance(category, RawPageReplayFailureCategory):
            raise TypeError("category expects RawPageReplayFailureCategory")
        self.category = category
        super().__init__(category.value)


@dataclass(frozen=True, repr=False)
class RawPageReplayCommand:
    request: ConfluenceRawPageOrphanInspectionRequest

    def __post_init__(self) -> None:
        if type(self.request) is not ConfluenceRawPageOrphanInspectionRequest:
            raise TypeError("request expects ConfluenceRawPageOrphanInspectionRequest")

    @classmethod
    def capture(
        cls,
        *,
        run_id: CrawlRunId,
        generation_id: CrawlRunId,
        page_id: str,
        source_version: str | None,
    ) -> Self:
        return cls(
            ConfluenceRawPageOrphanInspectionRequest.capture(
                run_id=run_id,
                generation_id=generation_id,
                page_id=page_id,
                source_version=source_version,
            )
        )

    def __repr__(self) -> str:
        return "RawPageReplayCommand()"


@dataclass(frozen=True, repr=False)
class RawPageReplayResult:
    decision: RawPageReplayDecision
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.decision, RawPageReplayDecision):
            raise TypeError("decision is invalid")
        if type(self.replayed) is not bool:
            raise TypeError("replayed is invalid")
        if self.replayed is not (self.decision is RawPageReplayDecision.REPLAYED):
            raise ValueError("replayed flag does not match decision")

    def __repr__(self) -> str:
        return f"RawPageReplayResult(decision={self.decision.value!r})"


# The long aliases keep the public boundary consistent with the other
# Confluence-specific M7 ports while retaining concise internal names.
ConfluenceRawPageReplayCommand = RawPageReplayCommand
ConfluenceRawPageReplayDecision = RawPageReplayDecision
ConfluenceRawPageReplayFailure = RawPageReplayFailure
ConfluenceRawPageReplayFailureCategory = RawPageReplayFailureCategory
ConfluenceRawPageReplayResult = RawPageReplayResult


@dataclass(frozen=True, repr=False)
class CheckpointReservationResult:
    """One durably consumed outbound-attempt budget unit."""

    reservation_sequence: int

    def __post_init__(self) -> None:
        if type(self.reservation_sequence) is not int or self.reservation_sequence < 0:
            raise ValueError("invalid reservation result")

    def __repr__(self) -> str:
        return "CheckpointReservationResult()"


@dataclass(frozen=True, repr=False)
class InventoryWorkItem:
    """The next typed inventory action selected by a checkpoint session."""

    run_id: CrawlRunId
    include_root_ordinal: int
    include_root_page_id: str
    kind: Literal["root", "window"]
    next_start: int | None
    page_size: int

    def __post_init__(self) -> None:
        try:
            run_id = _validated_run_id(self.run_id)
        except TypeError:
            raise TypeError("invalid inventory work") from None
        except ValueError:
            raise ValueError("invalid inventory work") from None
        if type(self.include_root_ordinal) is not int or self.include_root_ordinal < 0:
            raise ValueError("invalid inventory work")
        if (
            type(self.include_root_page_id) is not str
            or not self.include_root_page_id
        ):
            raise ValueError("invalid inventory work")
        if type(self.kind) is not str or self.kind not in ("root", "window"):
            raise ValueError("invalid inventory work")
        if self.kind == "root":
            if self.next_start is not None:
                raise ValueError("invalid inventory work")
        elif type(self.next_start) is not int or self.next_start < 0:
            raise ValueError("invalid inventory work")
        if type(self.page_size) is not int or self.page_size <= 0:
            raise ValueError("invalid inventory work")
        object.__setattr__(self, "run_id", run_id)

    def __repr__(self) -> str:
        # Do not echo run/root identities in generic operator output.
        return (
            "InventoryWorkItem("
            f"kind={self.kind!r}, next_start={self.next_start!r}, "
            f"page_size={self.page_size!r})"
        )


@dataclass(frozen=True, repr=False)
class CheckpointCommitResult:
    """The transition committed by a typed mutation and replay status."""

    transition: CommittedCheckpointTransition
    replayed: bool

    def __post_init__(self) -> None:
        if type(self.transition) is not CommittedCheckpointTransition:
            raise TypeError("transition expects CommittedCheckpointTransition")
        try:
            transition = CommittedCheckpointTransition(
                self.transition.run_id,
                self.transition.include_root_ordinal,
                self.transition.include_root_page_id,
                self.transition.from_progress,
                self.transition.to_progress,
                self.transition.sequence,
                self.transition.include_roots,
            )
        except Exception:
            raise ValueError("invalid checkpoint result") from None
        if type(self.replayed) is not bool:
            raise TypeError("replayed expects bool")
        object.__setattr__(self, "transition", transition)

    def __repr__(self) -> str:
        # The transition contains caller-controlled identities; keep repr safe.
        return f"CheckpointCommitResult(replayed={self.replayed!r})"


class ConfluenceCheckpointStatePort(Protocol):
    """Safe schema seam; later stages use C1-B facts, never untyped dicts.

    Future operations accept and return typed commands/results directly. The
    protocol intentionally exposes operation-specific methods, never a generic
    transaction or mutation callback.
    """

    def read_schema_state(self) -> CheckpointSchemaState: ...

    def reserve_outbound_attempt(
        self,
    ) -> CheckpointReservationResult | CheckpointOperationFailure: ...

    def check_outbound_attempt(
        self,
    ) -> CheckpointOperationFailure | None: ...

    def complete_session(self) -> None: ...

    def pause_session(self) -> None: ...

    def load_next_inventory_work(
        self,
    ) -> InventoryWorkItem | CheckpointOperationFailure | None: ...

    def commit_root_occurrence(
        self, command: InventoryRootCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure: ...

    def commit_inventory_window(
        self, command: InventoryWindowCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure: ...

    def replay_raw_page(
        self,
        command: RawPageReplayCommand,
        inspector: ConfluenceRawPageOrphanInspectionPort,
    ) -> RawPageReplayResult | RawPageReplayFailure: ...

    def stream_inventory_occurrences(
        self,
        *,
        batch_size: int = 256,
    ) -> Iterator[InventoryRootCommit | InventoryOccurrence]: ...
