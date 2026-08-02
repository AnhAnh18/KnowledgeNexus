"""Private M7-C2-B run selection and process-session lifecycle seam."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    ConfluenceCrawlFingerprint,
    _build_effective_crawl_input,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CanonicalIncludeRoots,
    CommittedCheckpointTransition,
    CrawlRunId,
    CrawlRunOperation,
    CrawlRunSnapshot,
    CrawlRunStatus,
    CrawlSessionId,
    IncludeRootProgress,
    InventoryRootCommit,
    InventoryPhaseStatus,
    ResumeExplicitRunId,
    ResumeUniqueIncompleteRun,
    StartNewRun,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_workspace import (
    _open_locked_checkpoint_workspace,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_state_session import (
    _CheckpointStateSession,
    _SessionLimits,
    _validate_durable_inventory_state,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointSchemaState,
    CheckpointStateError,
    InventoryWorkItem,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryWindowCommit,
)


_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$")


class _RunRegistryFailureCategory(StrEnum):
    RUN_OPERATION_INVALID = "run_operation_invalid"
    RUN_NOT_FOUND = "run_not_found"
    RUN_NOT_RESUMABLE = "run_not_resumable"
    RUN_MATCH_AMBIGUOUS = "run_match_ambiguous"
    INCOMPLETE_RUN_CONFLICT = "incomplete_run_conflict"


@dataclass(frozen=True, repr=False)
class _RunRegistryRequest:
    workspace: Path
    operation: CrawlRunOperation
    endpoint_url: str
    source_config: ConfluenceSourceConfig
    reliability_profile: Mapping[str, object]

    def __repr__(self) -> str:
        return "_RunRegistryRequest()"


@dataclass(frozen=True, repr=False)
class _RunActivated:
    snapshot: CrawlRunSnapshot
    session_id: CrawlSessionId
    _state: _CheckpointStateSession = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "_RunActivated()"

    def load_next_inventory_work(
        self,
    ) -> InventoryWorkItem | CheckpointOperationFailure | None:
        return self._state.load_next_inventory_work()

    def read_schema_state(self) -> CheckpointSchemaState:
        return self._state.read_schema_state()

    def commit_root_occurrence(
        self, command: InventoryRootCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        return self._state.commit_root_occurrence(command)

    def commit_inventory_window(
        self, command: InventoryWindowCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        return self._state.commit_inventory_window(command)

    def stream_inventory_occurrences(self):
        return self._state.stream_inventory_occurrences()

    def _invalidate(self) -> None:
        self._state._invalidate()


@dataclass(frozen=True, repr=False)
class _InventoryComplete:
    snapshot: CrawlRunSnapshot

    def __repr__(self) -> str:
        return "_InventoryComplete()"


@dataclass(frozen=True, repr=False)
class _RunRegistryFailure:
    category: _RunRegistryFailureCategory

    def __post_init__(self) -> None:
        if type(self.category) is not _RunRegistryFailureCategory:
            raise TypeError("invalid run registry failure")

    def __repr__(self) -> str:
        return "_RunRegistryFailure()"


_RunRegistryOutcome = _RunActivated | _InventoryComplete | _RunRegistryFailure


@dataclass(frozen=True, repr=False)
class _PendingActivation:
    snapshot: CrawlRunSnapshot
    session_id: CrawlSessionId
    limits: _SessionLimits


@dataclass(frozen=True, repr=False)
class _StoredRun:
    snapshot: CrawlRunSnapshot
    fingerprint_digest: str
    status: str
    active_session_id: str | None

    def __repr__(self) -> str:
        return "_StoredRun()"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _operation_value(operation: object) -> tuple[str, str | None] | None:
    """Accept exactly one exact C1-B operation shape before any I/O."""
    if type(operation) is StartNewRun:
        return ("start", None)
    if type(operation) is ResumeUniqueIncompleteRun:
        return ("unique", None)
    if type(operation) is ResumeExplicitRunId:
        try:
            run_id = CrawlRunId(operation.run_id.value)
        except Exception:
            return None
        if operation.run_id != run_id:
            return None
        return ("explicit", run_id.value)
    return None


def _validate_timestamp(value: object) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise ValueError("invalid durable timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ValueError("invalid durable timestamp") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z" != value:
        raise ValueError("invalid durable timestamp")
    return value


def _timestamp_from(value: object) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError("invalid clock")
    if value.utcoffset() != timedelta(0):
        raise ValueError("invalid clock")
    result = (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}T"
        f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}."
        f"{value.microsecond // 1000:03d}Z"
    )
    return _validate_timestamp(result)


def _new_uuid4(uuid4: Callable[[], uuid.UUID]) -> str:
    try:
        value = uuid4()
        if type(value) is not uuid.UUID or value.version != 4:
            raise ValueError("invalid generated id")
        return CrawlRunId(str(value)).value
    except Exception:
        raise ValueError("invalid generated id") from None


def _progress_from(value: object) -> IncludeRootProgress:
    if type(value) is not str:
        raise ValueError("invalid durable progress")
    try:
        return IncludeRootProgress(value)
    except ValueError:
        raise ValueError("invalid durable progress") from None


def _validated_session_id(value: object) -> str:
    """Durable session rows use the canonical UUIDv4 representation."""
    try:
        canonical = CrawlRunId(value).value
        CrawlSessionId(canonical)
        return canonical
    except Exception:
        raise ValueError("invalid durable session") from None


def _read_sessions(transaction: object, run_id: str) -> str | None:
    rows = transaction._fetchall(
        "SELECT session_id,status,started_at,ended_at,outcome_status,outcome_reason "
        "FROM crawl_sessions WHERE run_id=? ORDER BY started_at,session_id",
        (run_id,),
    )
    active: list[str] = []
    for row in rows:
        if type(row) is not tuple or len(row) != 6:
            raise ValueError("invalid durable session")
        session_id, status, started_at, ended_at, outcome_status, outcome_reason = row
        _new_session_id = _validated_session_id(session_id)
        _validate_timestamp(started_at)
        if status == "active":
            if ended_at is not None or outcome_status is not None or outcome_reason is not None:
                raise ValueError("invalid durable session")
            active.append(_new_session_id)
        elif status == "completed":
            if (
                _validate_timestamp(ended_at) != ended_at
                or outcome_status != "completed"
                or outcome_reason != "completed"
            ):
                raise ValueError("invalid durable session")
        elif status == "interrupted":
            if (
                _validate_timestamp(ended_at) != ended_at
                or outcome_status != "interrupted"
                or outcome_reason != "process_interrupted"
            ):
                raise ValueError("invalid durable session")
        elif status == "paused":
            if (
                _validate_timestamp(ended_at) != ended_at
                or outcome_status != "paused"
                or outcome_reason != "controlled_checkpoint_stop"
            ):
                raise ValueError("invalid durable session")
        else:
            raise ValueError("invalid durable session")
    if len(active) > 1:
        raise ValueError("multiple active sessions")
    return active[0] if active else None


def _read_stored_run(
    transaction: object,
    row: tuple,
    *,
    page_size: int | None = None,
    limits: _SessionLimits | None = None,
) -> _StoredRun:
    if type(row) is not tuple or len(row) != 6:
        raise ValueError("invalid durable run")
    run_value, generation_value, digest, status, phase, created_at = row
    run_id = CrawlRunId(run_value)
    generation_id = CrawlRunId(generation_value)
    fingerprint = ConfluenceCrawlFingerprint._from_digest(digest)
    if run_id != generation_id or status not in {"incomplete", "complete"}:
        raise ValueError("invalid durable run")
    if phase not in {"pending", "complete"}:
        raise ValueError("invalid durable run")
    _validate_timestamp(created_at)

    root_rows = transaction._fetchall(
        "SELECT include_root_ordinal,include_root_page_id FROM include_roots "
        "WHERE run_id=? ORDER BY include_root_ordinal",
        (run_id.value,),
    )
    root_ids: list[str] = []
    for ordinal, root_id in root_rows:
        if type(ordinal) is not int or ordinal != len(root_ids):
            raise ValueError("invalid durable roots")
        if type(root_id) is not str or not root_id:
            raise ValueError("invalid durable roots")
        root_ids.append(root_id)
    roots = CanonicalIncludeRoots(tuple(root_ids))
    if roots.root_ids != tuple(root_ids):
        raise ValueError("invalid durable roots")

    progress_rows = transaction._fetchall(
        "SELECT include_root_ordinal,progress,next_start,descendants_complete "
        "FROM root_progress WHERE run_id=? ORDER BY include_root_ordinal",
        (run_id.value,),
    )
    if len(progress_rows) != len(root_ids):
        raise ValueError("invalid durable progress")
    progress: list[IncludeRootProgress] = []
    for ordinal, literal, next_start, complete in progress_rows:
        if type(ordinal) is not int or ordinal != len(progress):
            raise ValueError("invalid durable progress")
        item = _progress_from(literal)
        if next_start is not None and (type(next_start) is not int or next_start < 0):
            raise ValueError("invalid durable progress")
        if type(complete) is not int or complete not in {0, 1}:
            raise ValueError("invalid durable progress")
        if (item is IncludeRootProgress.DESCENDANTS_COMPLETE) != (complete == 1):
            raise ValueError("invalid durable progress")
        if item in {IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED} and next_start is not None:
            raise ValueError("invalid durable progress")
        if item is IncludeRootProgress.DESCENDANTS_PENDING and next_start is None:
            raise ValueError("invalid durable progress")
        if item is IncludeRootProgress.DESCENDANTS_COMPLETE and next_start is not None:
            raise ValueError("invalid durable progress")
        progress.append(item)

    transition_rows = transaction._fetchall(
        "SELECT sequence,include_root_ordinal,from_progress,to_progress "
        "FROM checkpoint_transitions WHERE run_id=? ORDER BY sequence",
        (run_id.value,),
    )
    transitions: list[CommittedCheckpointTransition] = []
    for sequence, ordinal, from_progress, to_progress in transition_rows:
        if type(sequence) is not int or sequence != len(transitions):
            raise ValueError("invalid durable transition")
        if type(ordinal) is not int or ordinal < 0 or ordinal >= len(root_ids):
            raise ValueError("invalid durable transition")
        transitions.append(
            CommittedCheckpointTransition(
                run_id,
                ordinal,
                root_ids[ordinal],
                _progress_from(from_progress),
                _progress_from(to_progress),
                sequence,
                roots,
            )
        )

    inventory_phase = InventoryPhaseStatus(phase)
    # CrawlRunSnapshot deliberately models incomplete runs only. Rebuilding a
    # complete durable row with its inventory facts still validates those facts.
    snapshot = CrawlRunSnapshot(
        run_id=run_id,
        generation_id=generation_id,
        fingerprint=fingerprint,
        status=CrawlRunStatus.INCOMPLETE,
        inventory_phase=inventory_phase,
        include_roots=roots,
        root_progress=tuple(progress),
        transitions=tuple(transitions),
    )
    _validate_durable_inventory_state(
        transaction, run_id, roots, page_size=page_size, limits=limits
    )
    return _StoredRun(
        snapshot=snapshot,
        fingerprint_digest=digest,
        status=status,
        active_session_id=_read_sessions(transaction, run_id.value),
    )


def _activate_existing(
    transaction: object,
    stored: _StoredRun,
    uuid4: Callable[[], uuid.UUID],
    utc_now: Callable[[], datetime],
    limits: _SessionLimits,
) -> _PendingActivation:
    session_value = _new_uuid4(uuid4)
    started_at = _timestamp_from(utc_now())
    if stored.active_session_id is not None:
        transaction._execute(
            "UPDATE crawl_sessions SET status='interrupted',ended_at=?,"
            "outcome_status='interrupted',outcome_reason='process_interrupted' "
            "WHERE session_id=? AND run_id=? AND status='active'",
            (started_at, stored.active_session_id, stored.snapshot.run_id.value),
        )
        changed = transaction._fetchone("SELECT changes()")
        if changed != (1,):
            raise ValueError("missing active session")
    transaction._execute(
        "INSERT INTO crawl_sessions "
        "(session_id,run_id,status,started_at,ended_at,outcome_status,outcome_reason) "
        "VALUES (?,?,'active',?,NULL,NULL,NULL)",
        (session_value, stored.snapshot.run_id.value, started_at),
    )
    return _PendingActivation(stored.snapshot, CrawlSessionId(session_value), limits)


def _start_new(
    transaction: object,
    effective: object,
    uuid4: Callable[[], uuid.UUID],
    utc_now: Callable[[], datetime],
    limits: _SessionLimits,
) -> _RunRegistryOutcome | _PendingActivation:
    rows = transaction._fetchall(
        "SELECT run_id,generation_id,fingerprint_digest,status,inventory_phase,created_at "
        "FROM crawl_runs WHERE status='incomplete' ORDER BY run_id"
    )
    for row in rows:
        stored = _read_stored_run(transaction, row, limits=limits)
        if stored.fingerprint_digest == effective.fingerprint.value:
            return _RunRegistryFailure(
                _RunRegistryFailureCategory.INCOMPLETE_RUN_CONFLICT
            )

    run_value = _new_uuid4(uuid4)
    session_value = _new_uuid4(uuid4)
    created_at = _timestamp_from(utc_now())
    run_id = CrawlRunId(run_value)
    roots = CanonicalIncludeRoots(effective.canonical_include_root_ids)
    snapshot = CrawlRunSnapshot(
        run_id=run_id,
        generation_id=run_id,
        fingerprint=effective.fingerprint,
        status=CrawlRunStatus.INCOMPLETE,
        inventory_phase=InventoryPhaseStatus.PENDING,
        include_roots=roots,
        root_progress=(IncludeRootProgress.ROOT_PENDING,) * len(roots.root_ids),
    )
    transaction._execute(
        "INSERT INTO crawl_runs "
        "(run_id,generation_id,fingerprint_digest,status,inventory_phase,created_at) "
        "VALUES (?,?,?,'incomplete','pending',?)",
        (run_value, run_value, effective.fingerprint.value, created_at),
    )
    for ordinal, root_id in roots.ordinals:
        transaction._execute(
            "INSERT INTO include_roots (run_id,include_root_ordinal,include_root_page_id) "
            "VALUES (?,?,?)",
            (run_value, ordinal, root_id),
        )
        transaction._execute(
            "INSERT INTO root_progress "
            "(run_id,include_root_ordinal,progress,next_start,descendants_complete) "
            "VALUES (?,?,'root_pending',NULL,0)",
            (run_value, ordinal),
        )
    transaction._execute(
        "INSERT INTO crawl_sessions "
        "(session_id,run_id,status,started_at,ended_at,outcome_status,outcome_reason) "
        "VALUES (?,?,'active',?,NULL,NULL,NULL)",
        (session_value, run_value, created_at),
    )
    return _PendingActivation(snapshot, CrawlSessionId(session_value), limits)


@contextmanager
def _register_checkpoint_run(
    request: _RunRegistryRequest,
    *,
    uuid4: Callable[[], uuid.UUID] = uuid.uuid4,
    utc_now: Callable[[], datetime] = _utc_now,
) -> Iterator[_RunRegistryOutcome]:
    """Select one run and keep an activation's lock through the caller body."""
    selection = _operation_value(getattr(request, "operation", None))
    if selection is None:
        yield _RunRegistryFailure(_RunRegistryFailureCategory.RUN_OPERATION_INVALID)
        return
    if type(request) is not _RunRegistryRequest:
        raise TypeError("invalid run registry request")

    effective = _build_effective_crawl_input(
        request.endpoint_url, request.source_config, request.reliability_profile
    )
    roots = CanonicalIncludeRoots(effective.canonical_include_root_ids)
    limits = _SessionLimits(
        effective.inventory_page_size,
        effective.max_pages_per_run,
        effective.max_inventory_windows_per_root,
        effective.max_inventory_windows_per_run,
    )
    operation, selected_run_id = selection

    def mutate(transaction: object) -> _RunRegistryOutcome | _PendingActivation:
        if operation == "start":
            return _start_new(transaction, effective, uuid4, utc_now, limits)

        rows = transaction._fetchall(
            "SELECT run_id,generation_id,fingerprint_digest,status,inventory_phase,created_at "
            "FROM crawl_runs "
            + ("WHERE run_id=?" if operation == "explicit" else "WHERE status='incomplete'")
            + " ORDER BY run_id",
            (selected_run_id,) if operation == "explicit" else (),
        )
        if operation == "explicit":
            if not rows:
                return _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_FOUND)
            stored = _read_stored_run(
                transaction, rows[0], limits=limits
            )
            if (
                stored.status != "incomplete"
                or stored.fingerprint_digest != effective.fingerprint.value
                or stored.snapshot.include_roots != roots
            ):
                return _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_RESUMABLE)
            if stored.snapshot.inventory_phase is InventoryPhaseStatus.COMPLETE:
                return _InventoryComplete(stored.snapshot)
            return _activate_existing(transaction, stored, uuid4, utc_now, limits)

        matches: list[_StoredRun] = []
        for row in rows:
            stored = _read_stored_run(
                transaction, row, limits=limits
            )
            if (
                stored.fingerprint_digest == effective.fingerprint.value
                and stored.snapshot.include_roots == roots
            ):
                matches.append(stored)
        if not matches:
            return _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_FOUND)
        if len(matches) != 1:
            return _RunRegistryFailure(_RunRegistryFailureCategory.RUN_MATCH_AMBIGUOUS)
        stored = matches[0]
        if stored.snapshot.inventory_phase is InventoryPhaseStatus.COMPLETE:
            return _InventoryComplete(stored.snapshot)
        return _activate_existing(transaction, stored, uuid4, utc_now, limits)

    owner = ExitStack()
    try:
        try:
            workspace = owner.enter_context(
                _open_locked_checkpoint_workspace(
                    request.workspace, require_initialized=operation != "start"
                )
            )
        except CheckpointStateError as error:
            if (
                operation != "start"
                and getattr(error, "_missing_initial_database", False)
            ):
                yield _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_FOUND)
                return
            raise
        outcome = workspace._mutate(mutate)
        if type(outcome) is not _PendingActivation:
            owner.close()
            yield outcome
            return

        activation = _RunActivated(
            outcome.snapshot,
            outcome.session_id,
            _CheckpointStateSession(
                workspace,
                outcome.snapshot.run_id,
                outcome.session_id,
                outcome.snapshot.include_roots,
                outcome.limits,
            ),
        )
        body_failed = False
        try:
            yield activation
        except BaseException:
            body_failed = True
            raise
        finally:
            activation._invalidate()
            if body_failed:
                try:
                    owner.close()
                except BaseException:
                    pass
            else:
                owner.close()
    finally:
        try:
            owner.close()
        except BaseException:
            # The caller's exception, if any, must remain the one reported.
            pass


__all__ = []
