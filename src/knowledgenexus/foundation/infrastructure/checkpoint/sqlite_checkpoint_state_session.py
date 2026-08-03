"""Typed C2-C state operations inside the already-held writer lease."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CanonicalIncludeRoots,
    CommittedCheckpointTransition,
    CrawlRunId,
    IncludeRootProgress,
    InventoryPhaseStatus,
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
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionDecision,
    ConfluenceRawPageOrphanInspectionError,
    ConfluenceRawPageOrphanInspectionResult,
)
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_orphan_inspection import (
    ConfluenceRawRestrictionOrphanInspectionDecision,
    ConfluenceRawRestrictionOrphanInspectionError,
    ConfluenceRawRestrictionOrphanInspectionResult,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.ports.confluence_raw_page_orphan_inspection_port import (
    ConfluenceRawPageOrphanInspectionPort,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_orphan_inspection_port import (
    ConfluenceRawRestrictionOrphanInspectionPort,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointCommitResult,
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
    CheckpointReservationResult,
    CheckpointSchemaState,
    InventoryWorkItem,
    RawPageReplayCommand,
    RawPageReplayDecision,
    RawPageReplayFailure,
    RawPageReplayFailureCategory,
    RawPageReplayResult,
    RawRestrictionReplayCommand,
    RawRestrictionReplayDecision,
    RawRestrictionReplayFailure,
    RawRestrictionReplayFailureCategory,
    RawRestrictionReplayResult,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)


class _OperationCategory(StrEnum):
    STATE_CONFLICT = "state_conflict"
    INVENTORY_IDENTITY_CONFLICT = "inventory_identity_conflict"
    INVENTORY_METADATA_CONFLICT = "inventory_metadata_conflict"
    PAGINATION_INVALID = "pagination_invalid"
    INVENTORY_PAGE_BUDGET_EXHAUSTED = "inventory_page_budget_exhausted"
    INVENTORY_WINDOW_LIMIT_EXHAUSTED = "inventory_window_limit_exhausted"
    REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"


def _failure(category: _OperationCategory) -> CheckpointOperationFailure:
    return CheckpointOperationFailure(CheckpointOperationFailureCategory(category.value))


_RESERVATION_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_RAW_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _reservation_timestamp(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid reservation timestamp")
    utc = value.astimezone(timezone.utc)
    result = utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
    if not _RESERVATION_TIMESTAMP.fullmatch(result):
        raise ValueError("invalid reservation timestamp")
    return result


def _validate_reservation_timestamp(value: object) -> None:
    if type(value) is not str or not _RESERVATION_TIMESTAMP.fullmatch(value):
        raise ValueError("invalid durable reservation")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ValueError("invalid durable reservation") from None


def _json_tuple(value: object) -> str:
    return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))


def _metadata_values(metadata: ConfluencePageMetadata) -> tuple[object, ...]:
    return (
        metadata.page_id,
        metadata.title,
        metadata.space_key,
        metadata.parent_page_id,
        metadata.updated_at,
        metadata.source_version,
        _json_tuple(metadata.ancestor_page_ids),
        _json_tuple(metadata.ancestor_titles),
        _json_tuple(metadata.labels),
        metadata.attachment_count,
    )


def _decode_string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not str:
        raise ValueError("invalid durable metadata")
    decoded = json.loads(value)
    if type(decoded) is not list or any(type(item) is not str for item in decoded):
        raise ValueError("invalid durable metadata")
    return tuple(decoded)


def _metadata_from_values(row: tuple[object, ...]) -> ConfluencePageMetadata:
    if len(row) != 10:
        raise ValueError("invalid durable metadata")
    page_id, title, space_key, parent, updated, source, ancestor_ids, ancestor_titles, labels, attachments = row
    decoded_ancestor_ids = _decode_string_tuple(ancestor_ids)
    decoded_ancestor_titles = _decode_string_tuple(ancestor_titles)
    decoded_labels = _decode_string_tuple(labels)
    if len(decoded_ancestor_ids) != len(decoded_ancestor_titles):
        raise ValueError("invalid durable metadata")
    if decoded_ancestor_ids and parent != decoded_ancestor_ids[-1]:
        raise ValueError("invalid durable metadata")
    if not decoded_ancestor_ids and parent is not None:
        raise ValueError("invalid durable metadata")
    metadata = ConfluencePageMetadata(
        page_id,
        title,
        space_key,
        parent,
        decoded_ancestor_ids,
        decoded_ancestor_titles,
        updated,
        source,
        decoded_labels,
        attachments,
    )
    # Stored arrays must already be canonical; readback never repairs data.
    if metadata.ancestor_page_ids != decoded_ancestor_ids or metadata.ancestor_titles != decoded_ancestor_titles:
        raise ValueError("invalid durable metadata")
    if metadata.labels != decoded_labels:
        raise ValueError("invalid durable metadata")
    return metadata


def _transition(
    transaction: object,
    run_id: CrawlRunId,
    ordinal: int,
    root_id: str,
    from_progress: IncludeRootProgress,
    to_progress: IncludeRootProgress,
    include_roots: CanonicalIncludeRoots,
) -> CommittedCheckpointTransition:
    row = transaction._fetchone(
        "SELECT COALESCE(MAX(sequence), -1) + 1 FROM checkpoint_transitions WHERE run_id=?",
        (run_id.value,),
    )
    if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int:
        raise ValueError("invalid transition sequence")
    sequence = row[0]
    transaction._execute(
        "INSERT INTO checkpoint_transitions "
        "(run_id,sequence,include_root_ordinal,from_progress,to_progress) "
        "VALUES (?,?,?,?,?)",
        (run_id.value, sequence, ordinal, from_progress.value, to_progress.value),
    )
    return CommittedCheckpointTransition(
        run_id,
        ordinal,
        root_id,
        from_progress,
        to_progress,
        sequence,
        include_roots,
    )


def _existing_page_ids(transaction: object, run_id: CrawlRunId) -> set[str]:
    rows = transaction._fetchall(
        "SELECT page_id FROM root_occurrences WHERE run_id=? "
        "UNION SELECT page_id FROM inventory_occurrences WHERE run_id=?",
        (run_id.value, run_id.value),
    )
    result: set[str] = set()
    for row in rows:
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not str or not row[0]:
            raise ValueError("invalid durable page identity")
        result.add(row[0])
    return result


def _read_progress(transaction: object, run_id: CrawlRunId, ordinal: int) -> tuple[str, int | None, int] | None:
    row = transaction._fetchone(
        "SELECT progress,next_start,descendants_complete FROM root_progress "
        "WHERE run_id=? AND include_root_ordinal=?",
        (run_id.value, ordinal),
    )
    if row is None:
        return None
    if type(row) is not tuple or len(row) != 3:
        raise ValueError("invalid durable progress")
    progress, next_start, complete = row
    if type(progress) is not str or type(complete) is not int or complete not in (0, 1):
        raise ValueError("invalid durable progress")
    try:
        progress_value = IncludeRootProgress(progress)
    except ValueError:
        raise ValueError("invalid durable progress") from None
    if next_start is not None and (type(next_start) is not int or next_start < 0):
        raise ValueError("invalid durable progress")
    if (progress_value is IncludeRootProgress.DESCENDANTS_COMPLETE) != bool(complete):
        raise ValueError("invalid durable progress")
    if progress_value in (IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED) and next_start is not None:
        raise ValueError("invalid durable progress")
    if progress_value is IncludeRootProgress.DESCENDANTS_PENDING and next_start is None:
        raise ValueError("invalid durable progress")
    if progress_value is IncludeRootProgress.DESCENDANTS_COMPLETE and next_start is not None:
        raise ValueError("invalid durable progress")
    return progress_value.value, next_start, complete


def _validate_raw_page_progress(transaction: object) -> None:
    """Validate the exact-v1 raw linkage graph without repairing it."""
    rows = transaction._fetchall(
        "SELECT run_id,generation_id,page_id,request_profile_version,source_version,"
        "http_status,raw_sha256,byte_count,status,committed_at "
        "FROM raw_page_progress ORDER BY run_id,page_id"
    )
    known_runs = {
        row[0]
        for row in transaction._fetchall("SELECT run_id FROM crawl_runs")
        if type(row) is tuple and len(row) == 1 and type(row[0]) is str and row[0]
    }
    known_sources: dict[tuple[str, str], set[str | None]] = {}
    occurrence_rows = transaction._fetchall(
        "SELECT run_id,page_id,source_version FROM root_occurrences "
        "UNION ALL SELECT run_id,page_id,source_version FROM inventory_occurrences"
    )
    for occurrence in occurrence_rows:
        if (
            type(occurrence) is not tuple
            or len(occurrence) != 3
            or type(occurrence[0]) is not str
            or type(occurrence[1]) is not str
            or not occurrence[0]
            or not occurrence[1]
            or (
                occurrence[2] is not None
                and type(occurrence[2]) is not str
            )
        ):
            raise ValueError("invalid raw page inventory binding")
        known_sources.setdefault((occurrence[0], occurrence[1]), set()).add(
            occurrence[2]
        )
    for row in rows:
        if type(row) is not tuple or len(row) != 10:
            raise ValueError("invalid raw page progress")
        (
            run_value,
            generation_value,
            page_id,
            profile,
            source_version,
            http_status,
            raw_sha256,
            byte_count,
            status,
            committed_at,
        ) = row
        try:
            run_id = CrawlRunId(run_value)
            generation_id = CrawlRunId(generation_value)
        except Exception:
            raise ValueError("invalid raw page progress") from None
        if (
            run_id.value not in known_runs
            or run_id != generation_id
            or type(page_id) is not str
            or not page_id
            or known_sources.get((run_id.value, page_id)) != {source_version}
            or profile != M7_RAW_PAGE_REQUEST_PROFILE_VERSION
            or (
                source_version is not None
                and (
                    type(source_version) is not str
                    or not source_version
                    or len(source_version) > 256
                    or any(ord(char) < 0x20 or ord(char) == 0x7F for char in source_version)
                )
            )
            or isinstance(http_status, bool)
            or type(http_status) is not int
            or not 100 <= http_status <= 599
            or type(raw_sha256) is not str
            or _RAW_SHA256.fullmatch(raw_sha256) is None
            or type(byte_count) is not int
            or byte_count < 0
            or status != "committed"
        ):
            raise ValueError("invalid raw page progress")
        _validate_reservation_timestamp(committed_at)


def _restriction_inventory_linkage(
    transaction: object,
) -> dict[tuple[str, str], set[tuple[str, ...]]]:
    """Return canonical ancestor facts for every durable selected page."""
    rows = transaction._fetchall(
        "SELECT run_id,page_id,ancestor_page_ids_json FROM root_occurrences "
        "UNION ALL SELECT run_id,page_id,ancestor_page_ids_json FROM inventory_occurrences"
    )
    linkage: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    for row in rows:
        if (
            type(row) is not tuple
            or len(row) != 3
            or type(row[0]) is not str
            or not row[0]
            or type(row[1]) is not str
            or not row[1]
        ):
            raise ValueError("invalid restriction inventory binding")
        try:
            selected = row[1]
            ancestors = _decode_string_tuple(row[2])
        except (TypeError, ValueError):
            raise ValueError("invalid restriction inventory binding") from None
        linkage.setdefault((row[0], selected), set()).add(ancestors)
    return linkage


def _validate_raw_restriction_progress(transaction: object) -> None:
    """Validate exact-v1 restriction rows and their inventory ancestry graph."""
    rows = transaction._fetchall(
        "SELECT run_id,generation_id,selected_page_id,target_page_id,"
        "request_profile_version,http_status,raw_sha256,byte_count,status,committed_at "
        "FROM raw_restriction_progress ORDER BY run_id,selected_page_id,target_page_id"
    )
    if not rows:
        return
    known_runs = {
        row[0]
        for row in transaction._fetchall("SELECT run_id FROM crawl_runs")
        if type(row) is tuple and len(row) == 1 and type(row[0]) is str and row[0]
    }
    linkage = _restriction_inventory_linkage(transaction)
    for row in rows:
        if type(row) is not tuple or len(row) != 10:
            raise ValueError("invalid raw restriction progress")
        (
            run_value,
            generation_value,
            selected_page_id,
            target_page_id,
            profile,
            http_status,
            raw_sha256,
            byte_count,
            status,
            committed_at,
        ) = row
        try:
            run_id = CrawlRunId(run_value)
            generation_id = CrawlRunId(generation_value)
            selected = selected_page_id
            target = target_page_id
            if (
                type(selected) is not str
                or not selected
                or type(target) is not str
                or not target
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("invalid raw restriction progress") from None
        ancestors = linkage.get((run_id.value, selected))
        if (
            run_id.value not in known_runs
            or run_id != generation_id
            or not ancestors
            or not any(target == selected or target in values for values in ancestors)
            or profile != M7_RESTRICTION_REQUEST_PROFILE_VERSION
            or isinstance(http_status, bool)
            or type(http_status) is not int
            or http_status not in (200, 401, 403, 404)
            or type(raw_sha256) is not str
            or _RAW_SHA256.fullmatch(raw_sha256) is None
            or type(byte_count) is not int
            or byte_count < 0
            or status != "committed"
        ):
            raise ValueError("invalid raw restriction progress")
        _validate_reservation_timestamp(committed_at)


def _read_root_commit(
    transaction: object,
    run_id: CrawlRunId,
    ordinal: int,
    root_id: str,
    roots: CanonicalIncludeRoots,
) -> InventoryRootCommit | None:
    row = transaction._fetchone(
        "SELECT page_id,title,space_key,parent_page_id,updated_at,source_version,"
        "ancestor_page_ids_json,ancestor_titles_json,labels_json,attachment_count "
        "FROM root_occurrences WHERE run_id=? AND include_root_ordinal=?",
        (run_id.value, ordinal),
    )
    if row is None:
        return None
    if type(row) is not tuple:
        raise ValueError("invalid durable root")
    metadata = _metadata_from_values(row)
    return InventoryRootCommit(run_id, ordinal, root_id, metadata, roots)


def _read_window_commit(
    transaction: object,
    run_id: CrawlRunId,
    ordinal: int,
    root_id: str,
    roots: CanonicalIncludeRoots,
    requested_start: int,
    page_size: int,
) -> InventoryWindowCommit | None:
    window_row = transaction._fetchone(
        "SELECT requested_start,observed_start,response_size,total_size,next_start,terminal "
        "FROM inventory_windows WHERE run_id=? AND include_root_ordinal=? AND requested_start=?",
        (run_id.value, ordinal, requested_start),
    )
    if window_row is None:
        return None
    if type(window_row) is not tuple or len(window_row) != 6:
        raise ValueError("invalid durable window")
    stored_requested, observed_start, response_size, total_size, next_start, terminal = window_row
    if (
        type(stored_requested) is not int
        or type(observed_start) is not int
        or type(response_size) is not int
        or type(total_size) is not int
        or type(next_start) is not int
        or type(terminal) is not int
        or stored_requested != requested_start
        or observed_start != requested_start
        or requested_start < 0
        or observed_start < 0
        or response_size < 0
        or response_size > page_size
        or total_size < 0
        or next_start < 0
        or total_size < observed_start + response_size
        or next_start != observed_start + response_size
        or terminal not in (0, 1)
        or (terminal == 1) != (next_start >= total_size)
        or (response_size == 0 and terminal == 0)
    ):
        raise ValueError("invalid durable window")
    rows = transaction._fetchall(
        "SELECT window_start,item_ordinal,page_id,title,space_key,parent_page_id,"
        "updated_at,source_version,ancestor_page_ids_json,ancestor_titles_json,"
        "labels_json,attachment_count FROM inventory_occurrences "
        "WHERE run_id=? AND include_root_ordinal=? AND window_start=? ORDER BY item_ordinal",
        (run_id.value, ordinal, requested_start),
    )
    if len(rows) != response_size:
        raise ValueError("invalid durable occurrences")
    items: list[ConfluencePageMetadata] = []
    occurrences: list[InventoryOccurrence] = []
    for expected_ordinal, row in enumerate(rows):
        if type(row) is not tuple or len(row) != 12:
            raise ValueError("invalid durable occurrence")
        window_start, item_ordinal, page_id = row[:3]
        if window_start != requested_start or item_ordinal != expected_ordinal:
            raise ValueError("invalid durable occurrence")
        metadata = _metadata_from_values((page_id,) + row[3:])
        items.append(metadata)
        occurrences.append(
            InventoryOccurrence(
                run_id,
                ordinal,
                root_id,
                requested_start,
                expected_ordinal,
                page_id,
                metadata,
                roots,
            )
        )
    window = ConfluenceInventoryWindow(
        tuple(items), observed_start, page_size, response_size, total_size
    )
    if window.start + window.size != next_start or window.is_terminal != bool(terminal):
        raise ValueError("invalid durable window")
    return InventoryWindowCommit(
        run_id,
        ordinal,
        root_id,
        requested_start,
        window,
        tuple(occurrences),
        roots,
    )


@dataclass(frozen=True, repr=False)
class _SessionLimits:
    page_size: int
    max_pages_per_run: int
    max_windows_per_root: int
    max_windows_per_run: int
    max_total_requests_per_run: int

    def __repr__(self) -> str:
        return "_SessionLimits()"


class _CheckpointStateSession:
    """Operation-specific C2-C capability backed by one locked workspace."""

    __slots__ = (
        "_workspace",
        "_run_id",
        "_session_id",
        "_include_roots",
        "_limits",
        "_utc_now",
        "_active",
        "_observed_page_ids",
        "_commits_since_full_validation",
        "_last_data_version",
    )

    # Full graph validation is retained at activation, recovery, stream start,
    # and on a bounded cadence. Local checks remain transactionally fail-closed.
    _FULL_VALIDATION_INTERVAL = 64

    def __init__(
        self,
        workspace: object,
        run_id: CrawlRunId,
        session_id: object,
        include_roots: CanonicalIncludeRoots,
        limits: _SessionLimits,
        utc_now: Callable[[], datetime],
    ) -> None:
        self._workspace = workspace
        self._run_id = run_id
        self._session_id = session_id
        self._include_roots = include_roots
        self._limits = limits
        self._utc_now = utc_now
        self._active = True
        self._observed_page_ids: set[str] | None = None
        self._commits_since_full_validation = 0
        self._last_data_version: int | None = None

    def _require_active(self) -> None:
        if not self._active:
            raise CheckpointStateError() from None

    def _validate_active_session(self, transaction: object) -> None:
        row = transaction._fetchone(
            "SELECT run_id,status FROM crawl_sessions WHERE session_id=?",
            (self._session_id.value,),
        )
        if row != (self._run_id.value, "active"):
            raise ValueError("invalid active session")

    def _invalidate(self) -> None:
        self._active = False
        self._observed_page_ids = None
        self._last_data_version = None

    @staticmethod
    def _data_version(transaction: object) -> int:
        row = transaction._fetchone("PRAGMA data_version")
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int:
            raise ValueError("invalid database version")
        return row[0]

    def _validate_run_identity(self, transaction: object) -> None:
        row = transaction._fetchone(
            "SELECT generation_id FROM crawl_runs WHERE run_id=?",
            (self._run_id.value,),
        )
        if row != (self._run_id.value,):
            raise ValueError("invalid durable run identity")

    def _validate_inventory_local(
        self,
        transaction: object,
        *,
        ordinal: int | None = None,
        requested_start: int | None = None,
    ) -> None:
        """Check operation-local invariants between periodic graph scans."""
        self._validate_run_identity(transaction)
        self._validate_request_reservations(transaction)
        roots = transaction._fetchall(
            "SELECT include_root_ordinal,include_root_page_id FROM include_roots "
            "WHERE run_id=? ORDER BY include_root_ordinal",
            (self._run_id.value,),
        )
        if len(roots) != len(self._include_roots.root_ids):
            raise ValueError("invalid durable roots")
        for expected, row in enumerate(roots):
            if type(row) is not tuple or len(row) != 2 or row[0] != expected:
                raise ValueError("invalid durable roots")
            self._include_roots.validate(expected, row[1])
        progress_rows = transaction._fetchall(
            "SELECT include_root_ordinal,progress,next_start,descendants_complete "
            "FROM root_progress WHERE run_id=? ORDER BY include_root_ordinal",
            (self._run_id.value,),
        )
        if len(progress_rows) != len(roots):
            raise ValueError("invalid durable progress")
        for expected, row in enumerate(progress_rows):
            if type(row) is not tuple or len(row) != 4 or row[0] != expected:
                raise ValueError("invalid durable progress")
            checked = _read_progress(transaction, self._run_id, expected)
            if checked is None or checked[0] != row[1] or checked[1] != row[2]:
                raise ValueError("invalid durable progress")
        for expected, row in enumerate(progress_rows):
            latest = transaction._fetchone(
                "SELECT sequence,from_progress,to_progress FROM checkpoint_transitions "
                "WHERE run_id=? AND include_root_ordinal=? ORDER BY sequence DESC LIMIT 1",
                (self._run_id.value, expected),
            )
            progress_literal = row[1]
            if progress_literal == IncludeRootProgress.ROOT_PENDING.value:
                if latest is not None:
                    raise ValueError("invalid durable transition progress")
            else:
                if (
                    type(latest) is not tuple
                    or len(latest) != 3
                    or latest[2] != progress_literal
                ):
                    raise ValueError("invalid durable transition progress")
        phase = transaction._fetchone(
            "SELECT inventory_phase FROM crawl_runs WHERE run_id=?",
            (self._run_id.value,),
        )
        _validate_raw_page_progress(transaction)
        _validate_raw_restriction_progress(transaction)
        if phase not in ((InventoryPhaseStatus.PENDING.value,), (InventoryPhaseStatus.COMPLETE.value,)):
            raise ValueError("invalid inventory phase")
        expected_phase = (
            InventoryPhaseStatus.COMPLETE.value
            if progress_rows
            and all(row[1] == IncludeRootProgress.DESCENDANTS_COMPLETE.value for row in progress_rows)
            else InventoryPhaseStatus.PENDING.value
        )
        if phase != (expected_phase,):
            raise ValueError("invalid inventory phase")
        if ordinal is not None:
            if type(ordinal) is not int or ordinal < 0 or ordinal >= len(roots):
                raise ValueError("invalid inventory root")
            root_id = roots[ordinal][1]
            progress = _read_progress(transaction, self._run_id, ordinal)
            if progress is None:
                raise ValueError("invalid durable progress")
            root = _read_root_commit(
                transaction, self._run_id, ordinal, root_id, self._include_roots
            )
            if progress[0] == IncludeRootProgress.ROOT_PENDING.value and root is not None:
                raise ValueError("invalid root pending state")
            if progress[0] != IncludeRootProgress.ROOT_PENDING.value and root is None:
                raise ValueError("missing durable root")
            if requested_start is not None:
                window = _read_window_commit(
                    transaction,
                    self._run_id,
                    ordinal,
                    root_id,
                    self._include_roots,
                    requested_start,
                    self._limits.page_size,
                )
                if window is None and progress[0] == IncludeRootProgress.DESCENDANTS_PENDING.value:
                    if progress[1] != requested_start:
                        raise ValueError("invalid durable cursor")

    def _prepare_inventory_validation(
        self,
        transaction: object,
        *,
        ordinal: int | None = None,
        requested_start: int | None = None,
        force_full: bool = False,
    ) -> None:
        current_version = self._data_version(transaction)
        full = (
            force_full
            or self._last_data_version is None
            or current_version != self._last_data_version
            or self._commits_since_full_validation >= self._FULL_VALIDATION_INTERVAL
        )
        if full:
            self._validate_inventory(transaction)
            self._commits_since_full_validation = 0
            self._last_data_version = current_version
        else:
            self._validate_inventory_local(
                transaction, ordinal=ordinal, requested_start=requested_start
            )

    def _record_inventory_commit(self) -> None:
        self._commits_since_full_validation += 1

    def _page_ids(self, transaction: object) -> set[str]:
        """Rebuild once per activation under the process-lifetime writer lock."""
        if self._observed_page_ids is None:
            self._observed_page_ids = _existing_page_ids(transaction, self._run_id)
        return self._observed_page_ids

    def _page_ids_after_commit(self, page_ids: object) -> None:
        if self._observed_page_ids is None:
            raise ValueError("page budget cache was not initialized")
        for page_id in page_ids:
            if type(page_id) is not str or not page_id:
                raise ValueError("invalid committed page identity")
            self._observed_page_ids.add(page_id)

    def _validate_request_reservations(self, transaction: object) -> int:
        rows = transaction._fetchall(
            "SELECT run_id,reservation_sequence,reserved_at "
            "FROM request_budget_reservations "
            "ORDER BY run_id,reservation_sequence"
        )
        grouped: dict[str, list[tuple[int, str]]] = {}
        for row in rows:
            if type(row) is not tuple or len(row) != 3:
                raise ValueError("invalid durable reservation")
            run_value, sequence, reserved_at = row
            if type(run_value) is not str or not run_value:
                raise ValueError("invalid durable reservation")
            try:
                checked_run = CrawlRunId(run_value)
            except Exception:
                raise ValueError("invalid durable reservation") from None
            if type(sequence) is not int or sequence < 0:
                raise ValueError("invalid durable reservation")
            _validate_reservation_timestamp(reserved_at)
            grouped.setdefault(checked_run.value, []).append((sequence, reserved_at))

        known_runs = {
            row[0]
            for row in transaction._fetchall("SELECT run_id FROM crawl_runs")
            if type(row) is tuple and len(row) == 1 and type(row[0]) is str
        }
        if set(grouped) - known_runs:
            raise ValueError("invalid durable reservation")
        current = grouped.get(self._run_id.value, [])
        for run_value, items in grouped.items():
            if [sequence for sequence, _ in items] != list(range(len(items))):
                raise ValueError("invalid durable reservation")
            if run_value == self._run_id.value and len(items) > self._limits.max_total_requests_per_run:
                raise ValueError("request budget exceeded")
        return len(current)

    def _validate_inventory(self, transaction: object) -> None:
        """Fail closed when any durable inventory fact is missing or malformed."""
        self._validate_run_identity(transaction)
        self._validate_request_reservations(transaction)
        root_rows = transaction._fetchall(
            "SELECT include_root_ordinal,include_root_page_id FROM include_roots "
            "WHERE run_id=? ORDER BY include_root_ordinal",
            (self._run_id.value,),
        )
        if len(root_rows) != len(self._include_roots.root_ids):
            raise ValueError("invalid durable roots")
        for expected_ordinal, (ordinal, root_id) in enumerate(root_rows):
            if type(ordinal) is not int or ordinal != expected_ordinal:
                raise ValueError("invalid durable roots")
            self._include_roots.validate(ordinal, root_id)

        progress_rows = transaction._fetchall(
            "SELECT include_root_ordinal,progress,next_start,descendants_complete "
            "FROM root_progress WHERE run_id=? ORDER BY include_root_ordinal",
            (self._run_id.value,),
        )
        if len(progress_rows) != len(self._include_roots.root_ids):
            raise ValueError("invalid durable progress")
        progress: list[IncludeRootProgress] = []
        for ordinal, literal, next_start, complete in progress_rows:
            if type(ordinal) is not int or ordinal != len(progress):
                raise ValueError("invalid durable progress")
            checked = _read_progress(transaction, self._run_id, ordinal)
            if checked is None or checked[0] != literal or checked[1] != next_start:
                raise ValueError("invalid durable progress")
            if (checked[2] == 1) != (literal == IncludeRootProgress.DESCENDANTS_COMPLETE.value):
                raise ValueError("invalid durable progress")
            progress.append(IncludeRootProgress(literal))

        total_window_row = transaction._fetchone(
            "SELECT COUNT(*) FROM inventory_windows WHERE run_id=?",
            (self._run_id.value,),
        )
        if (
            type(total_window_row) is not tuple
            or len(total_window_row) != 1
            or type(total_window_row[0]) is not int
            or total_window_row[0] > self._limits.max_windows_per_run
        ):
            raise ValueError("inventory window budget exceeded")
        page_count = transaction._fetchone(
            "SELECT COUNT(*) FROM ("
            "SELECT page_id FROM root_occurrences WHERE run_id=? "
            "UNION SELECT page_id FROM inventory_occurrences WHERE run_id=?"
            ")",
            (self._run_id.value, self._run_id.value),
        )
        if (
            type(page_count) is not tuple
            or len(page_count) != 1
            or type(page_count[0]) is not int
            or page_count[0] > self._limits.max_pages_per_run
        ):
            raise ValueError("inventory page budget exceeded")
        orphan_rows = transaction._fetchone(
            "SELECT COUNT(*) FROM inventory_occurrences o "
            "LEFT JOIN inventory_windows w ON w.run_id=o.run_id "
            "AND w.include_root_ordinal=o.include_root_ordinal "
            "AND w.requested_start=o.window_start "
            "WHERE o.run_id=? AND w.run_id IS NULL",
            (self._run_id.value,),
        )
        if orphan_rows != (0,):
            raise ValueError("orphan durable occurrences")
        orphan_root_rows = transaction._fetchone(
            "SELECT COUNT(*) FROM root_occurrences r "
            "LEFT JOIN include_roots i ON i.run_id=r.run_id "
            "AND i.include_root_ordinal=r.include_root_ordinal "
            "WHERE r.run_id=? AND i.run_id IS NULL",
            (self._run_id.value,),
        )
        if orphan_root_rows != (0,):
            raise ValueError("orphan durable roots")
        orphan_window_rows = transaction._fetchone(
            "SELECT COUNT(*) FROM inventory_windows w "
            "LEFT JOIN include_roots i ON i.run_id=w.run_id "
            "AND i.include_root_ordinal=w.include_root_ordinal "
            "WHERE w.run_id=? AND i.run_id IS NULL",
            (self._run_id.value,),
        )
        if orphan_window_rows != (0,):
            raise ValueError("orphan durable windows")

        transition_rows = transaction._fetchall(
            "SELECT sequence,include_root_ordinal,from_progress,to_progress "
            "FROM checkpoint_transitions WHERE run_id=? ORDER BY sequence",
            (self._run_id.value,),
        )
        transitions: list[tuple[int, int, IncludeRootProgress, IncludeRootProgress]] = []
        for sequence, ordinal, from_progress, to_progress in transition_rows:
            if type(sequence) is not int or sequence != len(transitions):
                raise ValueError("invalid durable transition")
            if type(ordinal) is not int or ordinal < 0 or ordinal >= len(progress):
                raise ValueError("invalid durable transition")
            try:
                from_value = IncludeRootProgress(from_progress)
                to_value = IncludeRootProgress(to_progress)
            except ValueError:
                raise ValueError("invalid durable transition") from None
            if (from_value, to_value) not in {
                (IncludeRootProgress.ROOT_PENDING, IncludeRootProgress.ROOT_COMMITTED),
                (IncludeRootProgress.ROOT_COMMITTED, IncludeRootProgress.DESCENDANTS_PENDING),
                (IncludeRootProgress.DESCENDANTS_PENDING, IncludeRootProgress.DESCENDANTS_PENDING),
                (IncludeRootProgress.DESCENDANTS_PENDING, IncludeRootProgress.DESCENDANTS_COMPLETE),
            }:
                raise ValueError("invalid durable transition")
            transitions.append((sequence, ordinal, from_value, to_value))

        for ordinal, root_id in self._include_roots.ordinals:
            root = _read_root_commit(
                transaction, self._run_id, ordinal, root_id, self._include_roots
            )
            windows = transaction._fetchall(
                "SELECT requested_start FROM inventory_windows "
                "WHERE run_id=? AND include_root_ordinal=? ORDER BY requested_start",
                (self._run_id.value, ordinal),
            )
            if any(type(row) is not tuple or len(row) != 1 or type(row[0]) is not int for row in windows):
                raise ValueError("invalid durable windows")
            if len(windows) > self._limits.max_windows_per_root:
                raise ValueError("inventory window budget exceeded")
            if progress[ordinal] is IncludeRootProgress.ROOT_PENDING:
                if root is not None or windows:
                    raise ValueError("invalid root pending state")
            elif root is None:
                raise ValueError("missing durable root")

            previous_next = 0
            terminal_seen = False
            for row in windows:
                requested_start = row[0]
                if requested_start != previous_next or terminal_seen:
                    raise ValueError("invalid durable window cursor")
                commit = _read_window_commit(
                    transaction,
                    self._run_id,
                    ordinal,
                    root_id,
                    self._include_roots,
                    requested_start,
                    self._limits.page_size,
                )
                if commit is None:
                    raise ValueError("missing durable window")
                previous_next = commit.window.start + commit.window.size
                terminal_seen = commit.window.is_terminal
            if progress[ordinal] is IncludeRootProgress.ROOT_COMMITTED and windows:
                raise ValueError("invalid root committed windows")
            if progress[ordinal] is IncludeRootProgress.DESCENDANTS_PENDING:
                if windows:
                    if terminal_seen or progress_rows[ordinal][2] != previous_next:
                        raise ValueError("invalid descendants pending state")
                elif progress_rows[ordinal][2] != 0:
                    raise ValueError("invalid descendants pending state")
            if progress[ordinal] is IncludeRootProgress.DESCENDANTS_COMPLETE:
                if not windows or not terminal_seen or progress_rows[ordinal][2] is not None:
                    raise ValueError("invalid descendants complete state")

            root_transitions = [
                item for item in transitions if item[1] == ordinal
            ]
            expected = IncludeRootProgress.ROOT_PENDING
            for _, _, from_progress, to_progress in root_transitions:
                if from_progress is not expected:
                    raise ValueError("invalid durable transition continuity")
                expected = to_progress
            if expected is not progress[ordinal]:
                raise ValueError("invalid durable transition progress")
            root_edges = [item for item in root_transitions if item[2] is IncludeRootProgress.ROOT_PENDING]
            begin_edges = [item for item in root_transitions if item[2] is IncludeRootProgress.ROOT_COMMITTED]
            window_edges = [item for item in root_transitions if item[2] is IncludeRootProgress.DESCENDANTS_PENDING]
            has_desc_phase = progress[ordinal] in (
                IncludeRootProgress.DESCENDANTS_PENDING,
                IncludeRootProgress.DESCENDANTS_COMPLETE,
            )
            if len(root_edges) != int(root is not None) or len(begin_edges) != int(has_desc_phase):
                raise ValueError("invalid durable lifecycle transitions")
            if len(window_edges) != len(windows):
                raise ValueError("invalid durable window transitions")
            if windows:
                expected_terminal = (
                    IncludeRootProgress.DESCENDANTS_COMPLETE
                    if terminal_seen
                    else IncludeRootProgress.DESCENDANTS_PENDING
                )
                if window_edges[-1][3] is not expected_terminal:
                    raise ValueError("invalid durable terminal transition")
                if any(
                    edge[3] is IncludeRootProgress.DESCENDANTS_COMPLETE
                    for edge in window_edges[:-1]
                ):
                    raise ValueError("invalid durable terminal transition")
        phase = transaction._fetchone(
            "SELECT inventory_phase FROM crawl_runs WHERE run_id=?", (self._run_id.value,)
        )
        _validate_raw_page_progress(transaction)
        _validate_raw_restriction_progress(transaction)
        expected_phase = (
            InventoryPhaseStatus.COMPLETE.value
            if progress and all(item is IncludeRootProgress.DESCENDANTS_COMPLETE for item in progress)
            else InventoryPhaseStatus.PENDING.value
        )
        if phase != (expected_phase,):
            raise ValueError("invalid inventory phase")

    def _mutate(self, operation):
        self._require_active()
        try:
            return self._workspace._mutate(operation)
        except BaseException:
            self._invalidate()
            raise

    def read_schema_state(self) -> CheckpointSchemaState:
        self._require_active()

        def operation(transaction: object) -> CheckpointSchemaState:
            row = transaction._fetchone(
                "SELECT schema_version FROM checkpoint_metadata WHERE singleton=1"
            )
            if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int:
                raise ValueError("invalid schema state")
            return CheckpointSchemaState(row[0])

        return self._workspace._mutate(operation)

    def reserve_outbound_attempt(
        self,
    ) -> CheckpointReservationResult | CheckpointOperationFailure:
        self._require_active()

        def operation(transaction: object):
            self._validate_active_session(transaction)
            count = self._validate_request_reservations(transaction)
            if count >= self._limits.max_total_requests_per_run:
                return _failure(_OperationCategory.REQUEST_BUDGET_EXHAUSTED)
            timestamp = _reservation_timestamp(self._utc_now())
            transaction._execute(
                "INSERT INTO request_budget_reservations "
                "(run_id,reservation_sequence,reserved_at) VALUES (?,?,?)",
                (self._run_id.value, count, timestamp),
            )
            return CheckpointReservationResult(count)

        return self._workspace._mutate(operation)

    def check_outbound_attempt(self) -> CheckpointOperationFailure | None:
        self._require_active()

        def operation(transaction: object):
            self._validate_active_session(transaction)
            count = self._validate_request_reservations(transaction)
            if count >= self._limits.max_total_requests_per_run:
                return _failure(_OperationCategory.REQUEST_BUDGET_EXHAUSTED)
            return None

        return self._workspace._mutate(operation)

    def complete_session(self) -> None:
        self._require_active()

        def operation(transaction: object) -> None:
            self._validate_active_session(transaction)
            timestamp = _reservation_timestamp(self._utc_now())
            transaction._execute(
                "UPDATE crawl_sessions SET status='completed',ended_at=?,"
                "outcome_status='completed',outcome_reason='completed' "
                "WHERE session_id=? AND run_id=? AND status='active'",
                (timestamp, self._session_id.value, self._run_id.value),
            )
            if transaction._fetchone("SELECT changes()") != (1,):
                raise ValueError("active session changed")

        self._workspace._mutate(operation)

    def pause_session(self) -> None:
        self._require_active()

        def operation(transaction: object) -> None:
            self._validate_active_session(transaction)
            timestamp = _reservation_timestamp(self._utc_now())
            transaction._execute(
                "UPDATE crawl_sessions SET status='paused',ended_at=?,"
                "outcome_status='paused',outcome_reason='controlled_checkpoint_stop' "
                "WHERE session_id=? AND run_id=? AND status='active'",
                (timestamp, self._session_id.value, self._run_id.value),
            )
            if transaction._fetchone("SELECT changes()") != (1,):
                raise ValueError("active session changed")

        self._workspace._mutate(operation)

    def load_next_inventory_work(self) -> InventoryWorkItem | CheckpointOperationFailure | None:
        self._require_active()
        committed_transition = False

        def operation(transaction: object):
            nonlocal committed_transition
            self._prepare_inventory_validation(transaction)
            rows = transaction._fetchall(
                "SELECT r.include_root_ordinal,r.include_root_page_id,p.progress,p.next_start "
                "FROM include_roots r JOIN root_progress p ON p.run_id=r.run_id "
                "AND p.include_root_ordinal=r.include_root_ordinal WHERE r.run_id=? "
                "ORDER BY r.include_root_ordinal",
                (self._run_id.value,),
            )
            if len(rows) != len(self._include_roots.root_ids):
                raise ValueError("invalid durable work roots")
            for ordinal, root_id, progress, next_start in rows:
                self._include_roots.validate(ordinal, root_id)
                if progress == IncludeRootProgress.ROOT_PENDING.value:
                    return InventoryWorkItem(
                        self._run_id,
                        ordinal,
                        root_id,
                        "root",
                        None,
                        self._limits.page_size,
                    )
                if progress == IncludeRootProgress.ROOT_COMMITTED.value:
                    root_count = transaction._fetchone(
                        "SELECT COUNT(*) FROM inventory_windows WHERE run_id=? AND include_root_ordinal=?",
                        (self._run_id.value, ordinal),
                    )
                    run_count = transaction._fetchone(
                        "SELECT COUNT(*) FROM inventory_windows WHERE run_id=?",
                        (self._run_id.value,),
                    )
                    if root_count != (0,):
                        raise ValueError("invalid root window state")
                    if (
                        self._limits.max_windows_per_root <= 0
                        or run_count is None
                        or run_count[0] >= self._limits.max_windows_per_run
                    ):
                        return _failure(_OperationCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED)
                    transition = _transition(
                        transaction,
                        self._run_id,
                        ordinal,
                        root_id,
                        IncludeRootProgress.ROOT_COMMITTED,
                        IncludeRootProgress.DESCENDANTS_PENDING,
                        self._include_roots,
                    )
                    transaction._execute(
                        "UPDATE root_progress SET progress=?,next_start=?,descendants_complete=0 "
                        "WHERE run_id=? AND include_root_ordinal=? AND progress=?",
                        (
                            IncludeRootProgress.DESCENDANTS_PENDING.value,
                            0,
                            self._run_id.value,
                            ordinal,
                            IncludeRootProgress.ROOT_COMMITTED.value,
                        ),
                    )
                    if transaction._fetchone("SELECT changes()") != (1,):
                        raise ValueError("root progress changed")
                    committed_transition = True
                    return InventoryWorkItem(
                        self._run_id,
                        ordinal,
                        root_id,
                        "window",
                        0,
                        self._limits.page_size,
                    )
                if progress == IncludeRootProgress.DESCENDANTS_PENDING.value:
                    if type(next_start) is not int or next_start < 0:
                        raise ValueError("invalid durable cursor")
                    root_count = transaction._fetchone(
                        "SELECT COUNT(*) FROM inventory_windows WHERE run_id=? AND include_root_ordinal=?",
                        (self._run_id.value, ordinal),
                    )
                    run_count = transaction._fetchone(
                        "SELECT COUNT(*) FROM inventory_windows WHERE run_id=?",
                        (self._run_id.value,),
                    )
                    if (
                        root_count is None
                        or run_count is None
                        or root_count[0] >= self._limits.max_windows_per_root
                        or run_count[0] >= self._limits.max_windows_per_run
                    ):
                        return _failure(_OperationCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED)
                    return InventoryWorkItem(
                        self._run_id,
                        ordinal,
                        root_id,
                        "window",
                        next_start,
                        self._limits.page_size,
                    )
                if progress == IncludeRootProgress.DESCENDANTS_COMPLETE.value:
                    continue
                raise ValueError("invalid durable progress")
            return None

        result = self._mutate(operation)
        if committed_transition:
            self._record_inventory_commit()
        return result

    def commit_root_occurrence(
        self, command: InventoryRootCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        self._require_active()
        if type(command) is not InventoryRootCommit:
            raise TypeError("invalid root commit")
        try:
            canonical_command = InventoryRootCommit(
                command.run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                command.metadata,
                command.include_roots,
            )
        except Exception:
            raise ValueError("invalid root commit") from None
        if command != canonical_command:
            raise ValueError("invalid root commit")
        command = canonical_command
        if command.run_id != self._run_id or command.include_roots != self._include_roots:
            return _failure(_OperationCategory.INVENTORY_IDENTITY_CONFLICT)
        self._include_roots.validate(
            command.include_root_ordinal, command.include_root_page_id
        )

        def operation(transaction: object):
            self._prepare_inventory_validation(
                transaction, ordinal=command.include_root_ordinal
            )
            progress = _read_progress(
                transaction, self._run_id, command.include_root_ordinal
            )
            if progress is None:
                return _failure(_OperationCategory.STATE_CONFLICT)
            current = _read_root_commit(
                transaction,
                self._run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                self._include_roots,
            )
            if progress[0] != IncludeRootProgress.ROOT_PENDING.value:
                if current == command and progress[0] != IncludeRootProgress.ROOT_PENDING.value:
                    return CheckpointCommitResult(
                        _root_transition_for_replay(
                            transaction,
                            self._run_id,
                            command.include_root_ordinal,
                            command.include_root_page_id,
                            self._include_roots,
                        ),
                        True,
                    )
                return _failure(_OperationCategory.STATE_CONFLICT)
            if current is not None:
                return _failure(_OperationCategory.STATE_CONFLICT)
            existing = self._page_ids(transaction)
            if command.metadata.page_id not in existing and len(existing) + 1 > self._limits.max_pages_per_run:
                return _failure(_OperationCategory.INVENTORY_PAGE_BUDGET_EXHAUSTED)
            transaction._execute(
                "INSERT INTO root_occurrences "
                "(run_id,include_root_ordinal,page_id,title,space_key,parent_page_id,"
                "updated_at,source_version,ancestor_page_ids_json,ancestor_titles_json,"
                "labels_json,attachment_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self._run_id.value,
                    command.include_root_ordinal,
                    *_metadata_values(command.metadata),
                ),
            )
            transition = _transition(
                transaction,
                self._run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                IncludeRootProgress.ROOT_PENDING,
                IncludeRootProgress.ROOT_COMMITTED,
                self._include_roots,
            )
            transaction._execute(
                "UPDATE root_progress SET progress=? WHERE run_id=? AND include_root_ordinal=? "
                "AND progress=?",
                (
                    IncludeRootProgress.ROOT_COMMITTED.value,
                    self._run_id.value,
                    command.include_root_ordinal,
                    IncludeRootProgress.ROOT_PENDING.value,
                ),
            )
            if transaction._fetchone("SELECT changes()") != (1,):
                raise ValueError("root progress changed")
            return CheckpointCommitResult(transition, False)

        result = self._mutate(operation)
        if isinstance(result, CheckpointCommitResult) and not result.replayed:
            self._page_ids_after_commit((command.metadata.page_id,))
            self._record_inventory_commit()
        return result

    def commit_inventory_window(
        self, command: InventoryWindowCommit
    ) -> CheckpointCommitResult | CheckpointOperationFailure:
        self._require_active()
        if type(command) is not InventoryWindowCommit:
            raise TypeError("invalid inventory window commit")
        try:
            canonical_command = InventoryWindowCommit(
                command.run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                command.requested_start,
                command.window,
                command.occurrences,
                command.include_roots,
            )
        except Exception:
            raise ValueError("invalid inventory window commit") from None
        if command != canonical_command:
            raise ValueError("invalid inventory window commit")
        command = canonical_command
        if command.run_id != self._run_id or command.include_roots != self._include_roots:
            return _failure(_OperationCategory.INVENTORY_IDENTITY_CONFLICT)
        committed_page_ids = tuple(occurrence.page_id for occurrence in command.occurrences)
        self._include_roots.validate(
            command.include_root_ordinal, command.include_root_page_id
        )
        if command.window.limit != self._limits.page_size:
            return _failure(_OperationCategory.PAGINATION_INVALID)

        def operation(transaction: object):
            self._prepare_inventory_validation(
                transaction,
                ordinal=command.include_root_ordinal,
                requested_start=command.requested_start,
            )
            progress = _read_progress(
                transaction, self._run_id, command.include_root_ordinal
            )
            if progress is None:
                return _failure(_OperationCategory.STATE_CONFLICT)
            existing = _read_window_commit(
                transaction,
                self._run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                self._include_roots,
                command.requested_start,
                self._limits.page_size,
            )
            if existing is not None:
                try:
                    same = existing == command
                except Exception:
                    same = False
                if same:
                    return CheckpointCommitResult(
                        _window_transition_for_replay(
                            transaction,
                            self._run_id,
                            command.include_root_ordinal,
                            command.include_root_page_id,
                            command.requested_start,
                            self._include_roots,
                        ),
                        True,
                    )
                return _failure(_OperationCategory.INVENTORY_METADATA_CONFLICT)
            if progress[0] != IncludeRootProgress.DESCENDANTS_PENDING.value:
                return _failure(_OperationCategory.STATE_CONFLICT)
            if progress[1] != command.requested_start:
                return _failure(_OperationCategory.STATE_CONFLICT)
            root_count = transaction._fetchone(
                "SELECT COUNT(*) FROM inventory_windows WHERE run_id=? AND include_root_ordinal=?",
                (self._run_id.value, command.include_root_ordinal),
            )
            run_count = transaction._fetchone(
                "SELECT COUNT(*) FROM inventory_windows WHERE run_id=?",
                (self._run_id.value,),
            )
            if root_count is None or run_count is None or root_count[0] >= self._limits.max_windows_per_root or run_count[0] >= self._limits.max_windows_per_run:
                return _failure(_OperationCategory.INVENTORY_WINDOW_LIMIT_EXHAUSTED)
            existing_ids = self._page_ids(transaction)
            projected_ids = {occ.page_id for occ in command.occurrences}
            projected_new = projected_ids - existing_ids
            if len(existing_ids) + len(projected_new) > self._limits.max_pages_per_run:
                return _failure(_OperationCategory.INVENTORY_PAGE_BUDGET_EXHAUSTED)
            stored_next = command.window.start + command.window.size
            transaction._execute(
                "INSERT INTO inventory_windows "
                "(run_id,include_root_ordinal,requested_start,observed_start,response_size,"
                "total_size,next_start,terminal) VALUES (?,?,?,?,?,?,?,?)",
                (
                    self._run_id.value,
                    command.include_root_ordinal,
                    command.requested_start,
                    command.window.start,
                    command.window.size,
                    command.window.total_size,
                    stored_next,
                    int(command.window.is_terminal),
                ),
            )
            for occurrence in command.occurrences:
                transaction._execute(
                    "INSERT INTO inventory_occurrences "
                    "(run_id,include_root_ordinal,window_start,item_ordinal,page_id,title,"
                    "space_key,parent_page_id,updated_at,source_version,ancestor_page_ids_json,"
                    "ancestor_titles_json,labels_json,attachment_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self._run_id.value,
                        command.include_root_ordinal,
                        occurrence.window_start,
                        occurrence.item_ordinal,
                        *_metadata_values(occurrence.metadata),
                    ),
                )
            if command.window.is_terminal:
                to_progress = IncludeRootProgress.DESCENDANTS_COMPLETE
                next_start = None
                complete = 1
            else:
                to_progress = IncludeRootProgress.DESCENDANTS_PENDING
                next_start = stored_next
                complete = 0
            transition = _transition(
                transaction,
                self._run_id,
                command.include_root_ordinal,
                command.include_root_page_id,
                IncludeRootProgress.DESCENDANTS_PENDING,
                to_progress,
                self._include_roots,
            )
            transaction._execute(
                "UPDATE root_progress SET progress=?,next_start=?,descendants_complete=? "
                "WHERE run_id=? AND include_root_ordinal=? AND progress=? AND next_start=?",
                (
                    to_progress.value,
                    next_start,
                    complete,
                    self._run_id.value,
                    command.include_root_ordinal,
                    IncludeRootProgress.DESCENDANTS_PENDING.value,
                    command.requested_start,
                ),
            )
            if transaction._fetchone("SELECT changes()") != (1,):
                raise ValueError("root progress changed")
            if to_progress is IncludeRootProgress.DESCENDANTS_COMPLETE:
                remaining = transaction._fetchone(
                    "SELECT COUNT(*) FROM root_progress WHERE run_id=? AND progress<>?",
                    (self._run_id.value, IncludeRootProgress.DESCENDANTS_COMPLETE.value),
                )
                if remaining == (0,):
                    transaction._execute(
                        "UPDATE crawl_runs SET inventory_phase=? WHERE run_id=?",
                        (InventoryPhaseStatus.COMPLETE.value, self._run_id.value),
                    )
            return CheckpointCommitResult(transition, False)

        result = self._mutate(operation)
        if isinstance(result, CheckpointCommitResult) and not result.replayed:
            self._page_ids_after_commit(committed_page_ids)
            self._record_inventory_commit()
        return result

    def replay_raw_page(
        self,
        command: RawPageReplayCommand,
        inspector: ConfluenceRawPageOrphanInspectionPort,
    ) -> RawPageReplayResult | RawPageReplayFailure:
        """Replay one immutable raw-page artifact into the locked checkpoint."""
        self._require_active()
        if type(command) is not RawPageReplayCommand:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INVALID_REQUEST)
        if not callable(getattr(inspector, "inspect_raw_page", None)):
            return RawPageReplayFailure(RawPageReplayFailureCategory.INVALID_REQUEST)
        request = command.request
        if request.run_id != self._run_id or request.generation_id != self._run_id:
            return RawPageReplayResult(RawPageReplayDecision.IDENTITY_CONFLICT)
        try:
            self._mutate(
                lambda transaction: (
                    self._validate_active_session(transaction),
                    self._prepare_inventory_validation(transaction),
                )
            )
        except CheckpointStateError:
            raise
        except Exception:
            return RawPageReplayFailure(RawPageReplayFailureCategory.SCHEMA_INCOMPATIBLE)

        try:
            inspected = inspector.inspect_raw_page(request=request)
        except ConfluenceRawPageOrphanInspectionError:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED)
        except Exception:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED)
        if type(inspected) is not ConfluenceRawPageOrphanInspectionResult:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED)
        mapping = {
            ConfluenceRawPageOrphanInspectionDecision.MISSING: RawPageReplayDecision.MISSING,
            ConfluenceRawPageOrphanInspectionDecision.INVALID: RawPageReplayDecision.INVALID,
            ConfluenceRawPageOrphanInspectionDecision.IDENTITY_CONFLICT: RawPageReplayDecision.IDENTITY_CONFLICT,
            ConfluenceRawPageOrphanInspectionDecision.UNSAFE_TARGET: RawPageReplayDecision.UNSAFE_TARGET,
        }
        if inspected.decision in mapping:
            return RawPageReplayResult(mapping[inspected.decision])
        if inspected.decision is not ConfluenceRawPageOrphanInspectionDecision.REPLAYABLE:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED)
        envelope = inspected.envelope
        if envelope is None:
            return RawPageReplayResult(RawPageReplayDecision.IDENTITY_CONFLICT)
        try:
            artifact_bytes = envelope.to_bytes()
            envelope = ConfluenceRawPageEnvelope.from_bytes(artifact_bytes)
        except Exception:
            return RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED)
        if (
            envelope.request_profile_version != request.request_profile_version
            or envelope.run_id != request.run_id
            or envelope.generation_id != request.generation_id
            or envelope.page_id != request.page_id
            or envelope.source_version != request.source_version
        ):
            return RawPageReplayResult(RawPageReplayDecision.IDENTITY_CONFLICT)
        expected_hash = hashlib.sha256(artifact_bytes).hexdigest()
        expected_values = (
            envelope.generation_id.value,
            envelope.page_id,
            envelope.request_profile_version,
            envelope.source_version,
            envelope.http_status,
            expected_hash,
            len(artifact_bytes),
            "committed",
        )

        def operation(transaction: object) -> RawPageReplayResult:
            self._validate_active_session(transaction)
            self._prepare_inventory_validation(transaction)
            known_rows = transaction._fetchall(
                "SELECT source_version FROM root_occurrences WHERE run_id=? AND page_id=? "
                "UNION SELECT source_version FROM inventory_occurrences WHERE run_id=? AND page_id=?",
                (self._run_id.value, envelope.page_id, self._run_id.value, envelope.page_id),
            )
            if not known_rows:
                return RawPageReplayResult(RawPageReplayDecision.UNKNOWN_INVENTORY)
            if any(
                type(row) is not tuple or len(row) != 1 or row[0] != envelope.source_version
                for row in known_rows
            ):
                return RawPageReplayResult(RawPageReplayDecision.IDENTITY_CONFLICT)
            existing = transaction._fetchone(
                "SELECT generation_id,page_id,request_profile_version,source_version,"
                "http_status,raw_sha256,byte_count,status FROM raw_page_progress "
                "WHERE run_id=? AND page_id=?",
                (self._run_id.value, envelope.page_id),
            )
            if existing is not None:
                if existing == expected_values:
                    return RawPageReplayResult(RawPageReplayDecision.REPLAYED, True)
                return RawPageReplayResult(RawPageReplayDecision.CONFLICT)
            committed_at = _reservation_timestamp(self._utc_now())
            transaction._execute(
                "INSERT INTO raw_page_progress "
                "(run_id,generation_id,page_id,request_profile_version,source_version,"
                "http_status,raw_sha256,byte_count,status,committed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self._run_id.value, *expected_values, committed_at),
            )
            readback = transaction._fetchone(
                "SELECT generation_id,page_id,request_profile_version,source_version,"
                "http_status,raw_sha256,byte_count,status FROM raw_page_progress "
                "WHERE run_id=? AND page_id=?",
                (self._run_id.value, envelope.page_id),
            )
            if readback != expected_values:
                raise ValueError("raw page progress acknowledgement mismatch")
            return RawPageReplayResult(RawPageReplayDecision.COMMITTED)

        try:
            return self._mutate(operation)
        except CheckpointStateError:
            raise
        except Exception:
            return RawPageReplayFailure(RawPageReplayFailureCategory.SCHEMA_INCOMPATIBLE)

    def replay_raw_restriction(
        self,
        command: RawRestrictionReplayCommand,
        inspector: ConfluenceRawRestrictionOrphanInspectionPort,
    ) -> RawRestrictionReplayResult | RawRestrictionReplayFailure:
        """Replay one immutable restriction artifact into the locked checkpoint."""
        self._require_active()
        if type(command) is not RawRestrictionReplayCommand:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INVALID_REQUEST
            )
        if not callable(getattr(inspector, "inspect_restriction", None)):
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INVALID_REQUEST
            )
        request = command.request
        if request.run_id != self._run_id:
            return RawRestrictionReplayResult(RawRestrictionReplayDecision.IDENTITY_CONFLICT)
        try:
            self._mutate(
                lambda transaction: (
                    self._validate_active_session(transaction),
                    self._prepare_inventory_validation(transaction),
                )
            )
        except CheckpointStateError:
            raise
        except Exception:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.SCHEMA_INCOMPATIBLE
            )
        try:
            inspected = inspector.inspect_restriction(request=request)
        except ConfluenceRawRestrictionOrphanInspectionError:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INSPECTION_FAILED
            )
        except Exception:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INSPECTION_FAILED
            )
        if type(inspected) is not ConfluenceRawRestrictionOrphanInspectionResult:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INSPECTION_FAILED
            )
        mapping = {
            ConfluenceRawRestrictionOrphanInspectionDecision.MISSING: RawRestrictionReplayDecision.MISSING,
            ConfluenceRawRestrictionOrphanInspectionDecision.INVALID: RawRestrictionReplayDecision.INVALID,
            ConfluenceRawRestrictionOrphanInspectionDecision.IDENTITY_CONFLICT: RawRestrictionReplayDecision.IDENTITY_CONFLICT,
            ConfluenceRawRestrictionOrphanInspectionDecision.UNSAFE_TARGET: RawRestrictionReplayDecision.UNSAFE_TARGET,
        }
        if inspected.decision in mapping:
            return RawRestrictionReplayResult(mapping[inspected.decision])
        if inspected.decision is not ConfluenceRawRestrictionOrphanInspectionDecision.REPLAYABLE:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INSPECTION_FAILED
            )
        envelope = inspected.envelope
        if envelope is None:
            return RawRestrictionReplayResult(RawRestrictionReplayDecision.IDENTITY_CONFLICT)
        try:
            artifact_bytes = envelope.to_bytes()
            reparsed = ConfluenceRestrictionEvidenceEnvelope.from_bytes(artifact_bytes)
            if reparsed.to_bytes() != artifact_bytes:
                raise ValueError("restriction envelope is not canonical")
            envelope = reparsed
        except Exception:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.INSPECTION_FAILED
            )
        if (
            envelope.request_profile_version != request.request_profile_version
            or envelope.request_profile_version != M7_RESTRICTION_REQUEST_PROFILE_VERSION
            or envelope.selected_page_id != request.selected_page_id
            or envelope.target_page_id != request.target_page_id
        ):
            return RawRestrictionReplayResult(RawRestrictionReplayDecision.IDENTITY_CONFLICT)
        expected_hash = hashlib.sha256(artifact_bytes).hexdigest()
        expected_values = (
            self._run_id.value,
            envelope.selected_page_id,
            envelope.target_page_id,
            envelope.request_profile_version,
            envelope.http_status,
            expected_hash,
            len(artifact_bytes),
            "committed",
        )

        def operation(transaction: object) -> RawRestrictionReplayResult:
            self._validate_active_session(transaction)
            self._prepare_inventory_validation(transaction)
            linkage = _restriction_inventory_linkage(transaction)
            selected_key = (self._run_id.value, envelope.selected_page_id)
            ancestors = linkage.get(selected_key)
            if not ancestors:
                return RawRestrictionReplayResult(
                    RawRestrictionReplayDecision.UNKNOWN_INVENTORY
                )
            if not any(
                envelope.target_page_id == envelope.selected_page_id
                or envelope.target_page_id in values
                for values in ancestors
            ):
                return RawRestrictionReplayResult(
                    RawRestrictionReplayDecision.UNSAFE_TARGET
                )
            existing = transaction._fetchone(
                "SELECT generation_id,selected_page_id,target_page_id,"
                "request_profile_version,http_status,raw_sha256,byte_count,status "
                "FROM raw_restriction_progress WHERE run_id=? AND selected_page_id=? "
                "AND target_page_id=?",
                (
                    self._run_id.value,
                    envelope.selected_page_id,
                    envelope.target_page_id,
                ),
            )
            if existing is not None:
                if existing == expected_values:
                    return RawRestrictionReplayResult(
                        RawRestrictionReplayDecision.REPLAYED, True
                    )
                return RawRestrictionReplayResult(RawRestrictionReplayDecision.CONFLICT)
            committed_at = _reservation_timestamp(self._utc_now())
            transaction._execute(
                "INSERT INTO raw_restriction_progress "
                "(run_id,generation_id,selected_page_id,target_page_id,"
                "request_profile_version,http_status,raw_sha256,byte_count,status,committed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self._run_id.value, *expected_values, committed_at),
            )
            readback = transaction._fetchone(
                "SELECT generation_id,selected_page_id,target_page_id,"
                "request_profile_version,http_status,raw_sha256,byte_count,status "
                "FROM raw_restriction_progress WHERE run_id=? AND selected_page_id=? "
                "AND target_page_id=?",
                (
                    self._run_id.value,
                    envelope.selected_page_id,
                    envelope.target_page_id,
                ),
            )
            if readback != expected_values:
                raise ValueError("raw restriction progress acknowledgement mismatch")
            return RawRestrictionReplayResult(RawRestrictionReplayDecision.COMMITTED)

        try:
            return self._mutate(operation)
        except CheckpointStateError:
            raise
        except Exception:
            return RawRestrictionReplayFailure(
                RawRestrictionReplayFailureCategory.SCHEMA_INCOMPATIBLE
            )

    def stream_inventory_occurrences(
        self, *, batch_size: int = 256
    ) -> Iterator[InventoryRootCommit | InventoryOccurrence]:
        self._require_active()
        if type(batch_size) is not int or batch_size <= 0:
            raise CheckpointStateError() from None
        # Streaming is a trust boundary: always validate the complete graph.
        self._mutate(lambda transaction: self._prepare_inventory_validation(
            transaction, force_full=True
        ))

        def read_root(ordinal: int, root_id: str) -> InventoryRootCommit | None:
            return self._mutate(
                lambda transaction: _read_root_commit(
                    transaction,
                    self._run_id,
                    ordinal,
                    root_id,
                    self._include_roots,
                )
            )

        def read_batch(
            ordinal: int,
            root_id: str,
            continuation: tuple[int, int] | None,
        ) -> list[InventoryOccurrence]:
            def operation(transaction: object) -> list[InventoryOccurrence]:
                if continuation is None:
                    rows = transaction._fetchall(
                        "SELECT window_start,item_ordinal,page_id,title,space_key,parent_page_id,"
                        "updated_at,source_version,ancestor_page_ids_json,ancestor_titles_json,"
                        "labels_json,attachment_count FROM inventory_occurrences "
                        "WHERE run_id=? AND include_root_ordinal=? "
                        "ORDER BY window_start,item_ordinal LIMIT ?",
                        (self._run_id.value, ordinal, batch_size),
                    )
                else:
                    rows = transaction._fetchall(
                        "SELECT window_start,item_ordinal,page_id,title,space_key,parent_page_id,"
                        "updated_at,source_version,ancestor_page_ids_json,ancestor_titles_json,"
                        "labels_json,attachment_count FROM inventory_occurrences "
                        "WHERE run_id=? AND include_root_ordinal=? "
                        "AND (window_start>? OR (window_start=? AND item_ordinal>?)) "
                        "ORDER BY window_start,item_ordinal LIMIT ?",
                        (
                            self._run_id.value,
                            ordinal,
                            continuation[0],
                            continuation[0],
                            continuation[1],
                            batch_size,
                        ),
                    )
                result: list[InventoryOccurrence] = []
                for row in rows:
                    if type(row) is not tuple or len(row) != 12:
                        raise ValueError("invalid durable occurrence")
                    window_start, item_ordinal, page_id = row[:3]
                    metadata = _metadata_from_values((page_id,) + row[3:])
                    result.append(
                        InventoryOccurrence(
                            self._run_id,
                            ordinal,
                            root_id,
                            window_start,
                            item_ordinal,
                            page_id,
                            metadata,
                            self._include_roots,
                        )
                    )
                return result

            return self._mutate(operation)

        def iterator() -> Iterator[InventoryRootCommit | InventoryOccurrence]:
            self._require_active()
            root_index = 0
            root_emitted = False
            continuation: tuple[int, int] | None = None
            batch: list[InventoryOccurrence] = []
            batch_index = 0
            while root_index < len(self._include_roots.root_ids):
                self._require_active()
                ordinal, root_id = self._include_roots.ordinals[root_index]
                if not root_emitted:
                    root_emitted = True
                    root = read_root(ordinal, root_id)
                    if root is not None:
                        self._require_active()
                        yield root
                        continue
                if batch_index >= len(batch):
                    batch = read_batch(ordinal, root_id, continuation)
                    batch_index = 0
                    if not batch:
                        root_index += 1
                        root_emitted = False
                        continuation = None
                        batch = []
                        continue
                occurrence = batch[batch_index]
                batch_index += 1
                continuation = (occurrence.window_start, occurrence.item_ordinal)
                self._require_active()
                yield occurrence

        return iterator()


def _root_transition_for_replay(
    transaction: object,
    run_id: CrawlRunId,
    ordinal: int,
    root_id: str,
    roots: CanonicalIncludeRoots,
) -> CommittedCheckpointTransition:
    row = transaction._fetchone(
        "SELECT sequence,from_progress,to_progress FROM checkpoint_transitions "
        "WHERE run_id=? AND include_root_ordinal=? AND from_progress=? "
        "AND to_progress=? ORDER BY sequence LIMIT 1",
        (
            run_id.value,
            ordinal,
            IncludeRootProgress.ROOT_PENDING.value,
            IncludeRootProgress.ROOT_COMMITTED.value,
        ),
    )
    if type(row) is not tuple or len(row) != 3:
        raise ValueError("missing root transition")
    return CommittedCheckpointTransition(
        run_id,
        ordinal,
        root_id,
        IncludeRootProgress(row[1]),
        IncludeRootProgress(row[2]),
        row[0],
        roots,
    )


def _window_transition_for_replay(
    transaction: object,
    run_id: CrawlRunId,
    ordinal: int,
    root_id: str,
    requested_start: int,
    roots: CanonicalIncludeRoots,
) -> CommittedCheckpointTransition:
    rows = transaction._fetchall(
        "SELECT sequence,from_progress,to_progress FROM checkpoint_transitions "
        "WHERE run_id=? AND include_root_ordinal=? AND from_progress=? ORDER BY sequence",
        (run_id.value, ordinal, IncludeRootProgress.DESCENDANTS_PENDING.value),
    )
    windows = transaction._fetchall(
        "SELECT requested_start FROM inventory_windows WHERE run_id=? "
        "AND include_root_ordinal=? ORDER BY requested_start",
        (run_id.value, ordinal),
    )
    if len(rows) != len(windows):
        raise ValueError("invalid window transitions")
    starts = [row[0] for row in windows]
    try:
        index = starts.index(requested_start)
    except ValueError:
        raise ValueError("missing window transition") from None
    row = rows[index]
    if type(row) is not tuple or len(row) != 3:
        raise ValueError("invalid window transition")
    return CommittedCheckpointTransition(
        run_id,
        ordinal,
        root_id,
        IncludeRootProgress(row[1]),
        IncludeRootProgress(row[2]),
        row[0],
        roots,
    )


def _validate_durable_inventory_state(
    transaction: object,
    run_id: CrawlRunId,
    include_roots: CanonicalIncludeRoots,
    *,
    page_size: int | None = None,
    limits: _SessionLimits | None = None,
) -> None:
    """Validate durable inventory facts without exposing a session capability."""
    validator = object.__new__(_CheckpointStateSession)
    validator._workspace = None
    validator._run_id = run_id
    validator._session_id = None
    validator._include_roots = include_roots
    validator._limits = limits or _SessionLimits(
        page_size if page_size is not None else 2**31 - 1,
        2**63 - 1,
        2**63 - 1,
        2**63 - 1,
        2**63 - 1,
    )
    validator._active = True
    validator._validate_inventory(transaction)


__all__ = []
