from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import ContextManager
import uuid

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    ActivateRawGeneration,
    CrawlRunSnapshot,
    CrawlSessionId,
    ResumeExplicitRunId,
    ResumeUniqueIncompleteRun,
    StartNewRun,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    ActivateRawGenerationRequest,
    CheckpointRunInventoryComplete,
    CheckpointRunOutcome,
    CheckpointRunSelectionFailure,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointReservationResult,
    CheckpointSchemaState,
    InventoryWorkItem,
    CheckpointStateError,
    RawPageAcknowledgement,
    RawPageReplayCommand,
    RawPageReplayFailure,
    RawPageReplayResult,
    RawRestrictionReplayCommand,
    RawRestrictionReplayFailure,
    RawRestrictionReplayResult,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import InventoryRootCommit
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
    InventoryWindowCommit,
)
from knowledgenexus.foundation.ports.confluence_raw_page_orphan_inspection_port import (
    ConfluenceRawPageOrphanInspectionPort,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_orphan_inspection_port import (
    ConfluenceRawRestrictionOrphanInspectionPort,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _RunActivated,
    _RunRegistryFailure,
    _RunRegistryRequest,
    _InventoryComplete,
    _register_checkpoint_run,
)


_PUBLIC_ACTIVATIONS: dict[str, _RunActivated] = {}
_PUBLIC_STREAMS: dict[str, Iterator[InventoryRootCommit | InventoryOccurrence]] = {}


class _PublicInventoryIterator:
    __slots__ = ("_stream_id",)

    def __init__(self, stream: Iterator[InventoryRootCommit | InventoryOccurrence]) -> None:
        stream_id = uuid.uuid4().hex
        _PUBLIC_STREAMS[stream_id] = stream
        self._stream_id = stream_id

    def __iter__(self) -> _PublicInventoryIterator:
        return self

    def __next__(self) -> InventoryRootCommit | InventoryOccurrence:
        stream = _PUBLIC_STREAMS.get(self._stream_id)
        if stream is None:
            raise CheckpointStateError() from None
        try:
            return next(stream)
        except StopIteration:
            _PUBLIC_STREAMS.pop(self._stream_id, None)
            raise

    def _revoke(self) -> None:
        _PUBLIC_STREAMS.pop(self._stream_id, None)

    def __repr__(self) -> str:
        return "CheckpointInventoryIterator()"


class _PublicActivation:
    """Typed facade over the private lock-scoped activation capability."""

    __slots__ = ("_capability_id", "_stream_ids")

    def __init__(self, inner: _RunActivated) -> None:
        capability_id = uuid.uuid4().hex
        _PUBLIC_ACTIVATIONS[capability_id] = inner
        self._capability_id = capability_id
        self._stream_ids: set[str] = set()

    def _resolve(self) -> _RunActivated:
        try:
            return _PUBLIC_ACTIVATIONS[self._capability_id]
        except KeyError:
            raise CheckpointStateError() from None

    def _revoke(self) -> None:
        _PUBLIC_ACTIVATIONS.pop(self._capability_id, None)
        for stream_id in self._stream_ids:
            _PUBLIC_STREAMS.pop(stream_id, None)
        self._stream_ids.clear()

    @property
    def snapshot(self) -> CrawlRunSnapshot:
        return self._resolve().snapshot

    @property
    def session_id(self) -> CrawlSessionId:
        return self._resolve().session_id

    def read_schema_state(self) -> CheckpointSchemaState:
        return self._resolve().read_schema_state()

    def reserve_outbound_attempt(
        self,
    ) -> CheckpointReservationResult | CheckpointOperationFailure:
        return self._resolve().reserve_outbound_attempt()

    def check_outbound_attempt(self) -> CheckpointOperationFailure | None:
        return self._resolve().check_outbound_attempt()

    def complete_session(self) -> None:
        return self._resolve().complete_session()

    def pause_session(self) -> None:
        return self._resolve().pause_session()

    def load_next_inventory_work(self) -> InventoryWorkItem | CheckpointOperationFailure | None:
        return self._resolve().load_next_inventory_work()

    def commit_root_occurrence(
        self, command: InventoryRootCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        return self._resolve().commit_root_occurrence(command)

    def commit_inventory_window(
        self, command: InventoryWindowCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        return self._resolve().commit_inventory_window(command)

    def replay_raw_page(
        self,
        command: RawPageReplayCommand,
        inspector: ConfluenceRawPageOrphanInspectionPort,
    ) -> RawPageReplayResult | RawPageReplayFailure:
        return self._resolve().replay_raw_page(command, inspector)

    def acknowledge_raw_page(
        self, acknowledgement: RawPageAcknowledgement
    ) -> RawPageReplayResult | RawPageReplayFailure:
        return self._resolve().acknowledge_raw_page(acknowledgement)

    def guard_raw_publication(self):
        return self._resolve().guard_raw_publication()

    def replay_raw_restriction(
        self,
        command: RawRestrictionReplayCommand,
        inspector: ConfluenceRawRestrictionOrphanInspectionPort,
    ) -> RawRestrictionReplayResult | RawRestrictionReplayFailure:
        return self._resolve().replay_raw_restriction(command, inspector)

    def stream_inventory_occurrences(
        self, *, batch_size: int = 256
    ) -> Iterator[InventoryRootCommit | InventoryOccurrence]:
        stream = _PublicInventoryIterator(
            self._resolve().stream_inventory_occurrences(batch_size=batch_size)
        )
        self._stream_ids.add(stream._stream_id)
        return stream

    def __repr__(self) -> str:
        return "CheckpointRunActivation()"


class SqliteConfluenceCheckpointRunPort:
    """Public method-oriented adapter; SQLite and lock seams stay private."""

    @contextmanager
    def _activate(self, request: _RunRegistryRequest) -> Iterator[CheckpointRunOutcome]:
        with _register_checkpoint_run(request) as outcome:
            if isinstance(outcome, _RunActivated):
                public = _PublicActivation(outcome)
                try:
                    yield public
                finally:
                    public._revoke()
            elif isinstance(outcome, _InventoryComplete):
                yield CheckpointRunInventoryComplete(outcome.snapshot)
            elif isinstance(outcome, _RunRegistryFailure):
                yield CheckpointRunSelectionFailure(outcome.category.value)
            else:
                yield CheckpointRunSelectionFailure("run_operation_invalid")

    @staticmethod
    @contextmanager
    def _invalid_request() -> Iterator[CheckpointRunOutcome]:
        yield CheckpointRunSelectionFailure("run_operation_invalid")

    @staticmethod
    def _request(
        request: object,
        operation: object,
        expected_type: type,
    ) -> _RunRegistryRequest:
        if type(request) is not expected_type:
            raise TypeError("invalid checkpoint run request")
        return _RunRegistryRequest(
            request.workspace,
            operation,
            request.endpoint_url,
            request.source_config,
            dict(request.reliability_profile),
        )

    def start_new_run(self, request: StartNewRunRequest) -> ContextManager[CheckpointRunOutcome]:
        if type(request) is not StartNewRunRequest:
            return self._invalid_request()
        return self._activate(
            self._request(request, StartNewRun(), StartNewRunRequest)
        )

    def resume_explicit_run_id(
        self, request: ResumeExplicitRunRequest
    ) -> ContextManager[CheckpointRunOutcome]:
        if type(request) is not ResumeExplicitRunRequest:
            return self._invalid_request()
        return self._activate(
            self._request(request, ResumeExplicitRunId(request.run_id), ResumeExplicitRunRequest)
        )

    def resume_unique_incomplete_run(
        self, request: ResumeUniqueIncompleteRunRequest
    ) -> ContextManager[CheckpointRunOutcome]:
        if type(request) is not ResumeUniqueIncompleteRunRequest:
            return self._invalid_request()
        return self._activate(
            self._request(
                request,
                ResumeUniqueIncompleteRun(),
                ResumeUniqueIncompleteRunRequest,
            )
        )

    def activate_raw_generation(
        self, request: ActivateRawGenerationRequest
    ) -> ContextManager[CheckpointRunOutcome]:
        if type(request) is not ActivateRawGenerationRequest:
            return self._invalid_request()
        return self._activate(
            self._request(
                request,
                ActivateRawGeneration(request.run_id),
                ActivateRawGenerationRequest,
            )
        )


__all__ = []
