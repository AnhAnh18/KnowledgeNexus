"""Offline orchestration over the durable, typed Confluence checkpoint seams."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    build_confluence_crawl_fingerprint,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CrawlRunSnapshot,
    InventoryRootCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
    InventoryWindowCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.application.use_cases.controlled_checkpoint_stop import (
    ControlledStopController,
    ControlledStopPolicy,
    is_inventory_window_commit,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunInventoryComplete,
    CheckpointRunOutcome,
    CheckpointRunSelectionFailure,
    ConfluenceCheckpointRunPort,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointStateError,
    ConfluenceCheckpointStatePort,
    InventoryWorkItem,
)
from knowledgenexus.foundation.ports.confluence_inventory_window_port import (
    ConfluenceInventoryWindowPort,
)


DurableInventoryRequest = (
    StartNewRunRequest
    | ResumeExplicitRunRequest
    | ResumeUniqueIncompleteRunRequest
)


class DurableInventoryTransport(Protocol):
    def get_json(
        self, *, path: str, query: Mapping[str, str]
    ) -> Mapping[str, object]: ...

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes: ...

    def get_response_bytes(self, *, path: str, query: Mapping[str, str]) -> object: ...


class DurableInventoryWindowPortFactory(Protocol):
    def __call__(
        self, transport: DurableInventoryTransport
    ) -> ConfluenceInventoryWindowPort: ...


class DurableInventoryTransportFactory(Protocol):
    def __call__(
        self, activation: ConfluenceCheckpointStatePort
    ) -> DurableInventoryTransport: ...


@dataclass(frozen=True, repr=False)
class DurableInventoryRunResult:
    """Sanitized orchestration result; no activation or infrastructure handle."""

    status: Literal[
        "completed",
        "inventory_complete",
        "selection_failed",
        "operation_failed",
        "paused",
    ]
    committed: tuple[CheckpointCommitResult, ...] = ()
    selection_failure: CheckpointRunSelectionFailure | None = None
    operation_failure: CheckpointOperationFailure | None = None
    snapshot: CrawlRunSnapshot | None = None
    reason: Literal["controlled_checkpoint_stop"] | None = None
    controlled_stop_committed_count: int | None = None
    controlled_stop_threshold: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "completed",
            "inventory_complete",
            "selection_failed",
            "operation_failed",
            "paused",
        }:
            raise ValueError("invalid durable inventory result")
        try:
            committed = tuple(self.committed)
        except TypeError:
            raise TypeError("invalid durable inventory result") from None
        if any(type(item) is not CheckpointCommitResult for item in committed):
            raise TypeError("invalid durable inventory result")
        if self.status == "paused":
            if self.reason != "controlled_checkpoint_stop":
                raise ValueError("invalid durable inventory result")
            if (
                type(self.controlled_stop_committed_count) is not int
                or self.controlled_stop_committed_count < 0
                or type(self.controlled_stop_threshold) is not int
                or self.controlled_stop_threshold <= 0
                or (
                    self.controlled_stop_committed_count < self.controlled_stop_threshold
                )
            ):
                raise ValueError("invalid durable inventory result")
            if (
                type(self.snapshot) is not CrawlRunSnapshot
                or self.selection_failure is not None
                or self.operation_failure is not None
            ):
                raise ValueError("invalid durable inventory result")
            actual_window_commits = sum(
                not item.replayed
                and is_inventory_window_commit(item.transition)
                for item in committed
            )
            if actual_window_commits != self.controlled_stop_committed_count:
                raise ValueError("invalid durable inventory result")
        elif self.status == "selection_failed":
            if type(self.selection_failure) is not CheckpointRunSelectionFailure:
                raise ValueError("invalid durable inventory result")
            if (
                self.operation_failure is not None
                or self.reason is not None
                or self.controlled_stop_committed_count is not None
                or self.controlled_stop_threshold is not None
                or self.snapshot is not None
                or committed
            ):
                raise ValueError("invalid durable inventory result")
        elif self.status == "operation_failed":
            if type(self.operation_failure) is not CheckpointOperationFailure:
                raise ValueError("invalid durable inventory result")
            if (
                self.selection_failure is not None
                or self.reason is not None
                or self.controlled_stop_committed_count is not None
                or self.controlled_stop_threshold is not None
                or type(self.snapshot) is not CrawlRunSnapshot
            ):
                raise ValueError("invalid durable inventory result")
        elif (
            self.selection_failure is not None
            or self.operation_failure is not None
            or self.reason is not None
            or self.controlled_stop_committed_count is not None
            or self.controlled_stop_threshold is not None
        ):
            raise ValueError("invalid durable inventory result")
        if self.snapshot is not None and type(self.snapshot) is not CrawlRunSnapshot:
            raise TypeError("invalid durable inventory result")
        if self.status in {"completed", "inventory_complete"} and type(
            self.snapshot
        ) is not CrawlRunSnapshot:
            raise ValueError("invalid durable inventory result")
        if self.status == "inventory_complete" and committed:
            raise ValueError("invalid durable inventory result")
        object.__setattr__(self, "committed", committed)

    def __repr__(self) -> str:
        return (
            f"DurableInventoryRunResult(status={self.status!r}, "
            f"committed_count={len(self.committed)})"
        )


class ExecuteDurableConfluenceInventory:
    """Run one offline durable inventory step-loop to completion."""

    def __init__(
        self,
        *,
        checkpoint_run_port: ConfluenceCheckpointRunPort,
        inventory_window_port_factory: DurableInventoryWindowPortFactory,
        inventory_transport_factory: DurableInventoryTransportFactory,
    ) -> None:
        if not callable(getattr(checkpoint_run_port, "start_new_run", None)):
            raise TypeError("checkpoint_run_port must be a run port")
        if not callable(inventory_window_port_factory):
            raise TypeError("inventory_window_port_factory must be callable")
        if not callable(inventory_transport_factory):
            raise TypeError("inventory_transport_factory must be callable")
        self._checkpoint_run_port = checkpoint_run_port
        self._inventory_window_port_factory = inventory_window_port_factory
        self._inventory_transport_factory = inventory_transport_factory

    def execute(
        self,
        *,
        request: DurableInventoryRequest,
        controlled_stop_policy: ControlledStopPolicy | None = None,
    ) -> DurableInventoryRunResult:
        if type(request) not in (
            StartNewRunRequest,
            ResumeExplicitRunRequest,
            ResumeUniqueIncompleteRunRequest,
        ):
            raise CheckpointStateError() from None
        if controlled_stop_policy is None:
            controlled_stop_policy = ControlledStopPolicy()
        elif type(controlled_stop_policy) is not ControlledStopPolicy:
            raise TypeError("controlled_stop_policy must be ControlledStopPolicy or None")
        try:
            build_confluence_crawl_fingerprint(
                request.endpoint_url,
                request.source_config,
                request.reliability_profile,
            )
        except (TypeError, ValueError):
            raise CheckpointStateError() from None
        context = self._select_context(request)
        source_config = request.source_config
        committed: list[CheckpointCommitResult] = []
        stop_controller = ControlledStopController(controlled_stop_policy)

        with context as outcome:
            if isinstance(outcome, CheckpointRunSelectionFailure):
                return DurableInventoryRunResult(
                    "selection_failed", selection_failure=outcome
                )
            if isinstance(outcome, CheckpointRunInventoryComplete):
                return DurableInventoryRunResult(
                    "inventory_complete", snapshot=outcome.snapshot
                )
            activation = outcome
            window_port = self._window_port(activation)

            while True:
                work = activation.load_next_inventory_work()
                if work is None:
                    return DurableInventoryRunResult(
                        "completed", tuple(committed), snapshot=activation.snapshot
                    )
                if isinstance(work, CheckpointOperationFailure):
                    return DurableInventoryRunResult(
                        "operation_failed",
                        committed=tuple(committed),
                        operation_failure=work,
                        snapshot=activation.snapshot,
                    )
                if type(work) is not InventoryWorkItem:
                    raise CheckpointStateError() from None
                if work.run_id != activation.snapshot.run_id:
                    raise CheckpointStateError() from None

                if work.kind == "root":
                    metadata = window_port.fetch_root_metadata(
                        space_key=source_config.space_key,
                        root_page_id=work.include_root_page_id,
                    )
                    command = self._root_command(activation, work, metadata)
                    result = activation.commit_root_occurrence(command)
                else:
                    if work.next_start is None:
                        raise CheckpointStateError() from None
                    window = window_port.fetch_descendants_window(
                        space_key=source_config.space_key,
                        root_page_id=work.include_root_page_id,
                        start=work.next_start,
                        page_size=work.page_size,
                    )
                    command = self._window_command(activation, work, window)
                    result = activation.commit_inventory_window(command)

                if isinstance(result, CheckpointOperationFailure):
                    return DurableInventoryRunResult(
                        "operation_failed",
                        committed=tuple(committed),
                        operation_failure=result,
                        snapshot=activation.snapshot,
                    )
                if type(result) is not CheckpointCommitResult:
                    raise CheckpointStateError() from None
                committed.append(result)
                decision = stop_controller.record(result)
                if decision.status == "pause":
                    return DurableInventoryRunResult(
                        "paused",
                        reason=decision.reason,
                        controlled_stop_committed_count=decision.committed_count,
                        controlled_stop_threshold=decision.threshold,
                        committed=tuple(committed),
                        snapshot=activation.snapshot,
                    )

    def _select_context(
        self,
        request: DurableInventoryRequest,
    ) -> AbstractContextManager[CheckpointRunOutcome]:
        if type(request) is StartNewRunRequest:
            return self._checkpoint_run_port.start_new_run(request)
        if type(request) is ResumeExplicitRunRequest:
            return self._checkpoint_run_port.resume_explicit_run_id(request)
        if type(request) is ResumeUniqueIncompleteRunRequest:
            return self._checkpoint_run_port.resume_unique_incomplete_run(request)
        raise CheckpointStateError() from None

    def _window_port(
        self, activation: ConfluenceCheckpointStatePort
    ) -> ConfluenceInventoryWindowPort:
        transport = self._inventory_transport_factory(activation)
        port = self._inventory_window_port_factory(transport)
        if port is None or not callable(getattr(port, "fetch_root_metadata", None)):
            raise CheckpointStateError() from None
        if not callable(getattr(port, "fetch_descendants_window", None)):
            raise CheckpointStateError() from None
        return port

    @staticmethod
    def _root_command(
        activation: ConfluenceCheckpointStatePort,
        work: InventoryWorkItem,
        metadata: object,
    ) -> InventoryRootCommit:
        if type(metadata) is not ConfluencePageMetadata:
            raise CheckpointStateError() from None
        try:
            return InventoryRootCommit(
                work.run_id,
                work.include_root_ordinal,
                work.include_root_page_id,
                metadata,
                activation.snapshot.include_roots,
            )
        except Exception:
            raise CheckpointStateError() from None

    @staticmethod
    def _window_command(
        activation: ConfluenceCheckpointStatePort,
        work: InventoryWorkItem,
        window: object,
    ) -> InventoryWindowCommit:
        if type(window) is not ConfluenceInventoryWindow or window.start != work.next_start:
            raise CheckpointStateError() from None
        try:
            occurrences = tuple(
                InventoryOccurrence(
                    work.run_id,
                    work.include_root_ordinal,
                    work.include_root_page_id,
                    window.start,
                    ordinal,
                    metadata.page_id,
                    metadata,
                    activation.snapshot.include_roots,
                )
                for ordinal, metadata in enumerate(window.items)
            )
            return InventoryWindowCommit(
                work.run_id,
                work.include_root_ordinal,
                work.include_root_page_id,
                work.next_start,
                window,
                occurrences,
                activation.snapshot.include_roots,
            )
        except Exception:
            raise CheckpointStateError() from None
__all__ = [
    "DurableInventoryRunResult",
    "DurableInventoryTransport",
    "DurableInventoryTransportFactory",
    "ExecuteDurableConfluenceInventory",
]
