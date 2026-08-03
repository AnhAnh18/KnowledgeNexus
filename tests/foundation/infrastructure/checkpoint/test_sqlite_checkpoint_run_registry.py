from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    InventoryRootCommit,
    ResumeExplicitRunId,
    ResumeUniqueIncompleteRun,
    StartNewRun,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryWindowCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_window import (
    ConfluenceInventoryWindow,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.checkpoint import (
    sqlite_checkpoint_workspace as workspace_module,
)
from knowledgenexus.foundation.infrastructure.checkpoint import (
    sqlite_checkpoint_run_registry as registry_module,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _InventoryComplete,
    _RunActivated,
    _RunRegistryFailure,
    _RunRegistryFailureCategory,
    _RunRegistryRequest,
    _register_checkpoint_run as _register_checkpoint_run_context,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import CheckpointStateError


PROFILE = {
    "profile_id": "m7-crawl-reliability-v1",
    "profile_version": "1",
    "inventory_page_size": 50,
    "attachment_page_size": 50,
    "minimum_request_interval_seconds": 3.0,
    "max_response_bytes_per_request": 8388608,
    "max_total_requests_per_run": 50000,
    "max_attempts": 4,
    "base_backoff_seconds": 1.0,
    "max_retry_delay_seconds": 120.0,
    "max_total_retry_delay_seconds": 300.0,
    "jitter": False,
    "max_include_roots": 16,
    "max_pages_per_run": 10000,
    "max_inventory_windows_per_root": 1000,
    "max_inventory_windows_per_run": 4000,
    "max_restriction_targets_per_page": 256,
    "max_restriction_observations_per_run": 25000,
    "max_attachment_windows_per_page": 100,
    "max_attachment_windows_per_run": 10000,
    "max_raw_bytes_per_run": 34359738368,
    "max_raw_artifacts_per_run": 250000,
    "minimum_free_disk_reserve_bytes": 8589934592,
}


def _request(workspace, operation, *, root_ids=("b", "a"), endpoint_url=None):
    return _RunRegistryRequest(
        workspace=workspace,
        operation=operation,
        endpoint_url=endpoint_url or "https://example.invalid/confluence",
        source_config=ConfluenceSourceConfig(
            source_id="source",
            space_key="SPACE",
            include_roots=tuple(ConfluenceIncludeRoot(root_id) for root_id in root_ids),
        ),
        reliability_profile=dict(PROFILE),
    )


def _ids(*values: str):
    iterator = iter(values)
    return lambda: uuid.UUID(next(iterator))


def _clock() -> datetime:
    return datetime(2026, 8, 1, 1, 2, 3, 456789, tzinfo=timezone.utc)


def _register_checkpoint_run(*args, **kwargs):
    with _register_checkpoint_run_context(*args, **kwargs) as outcome:
        return outcome


def _assert_sanitized(error: CheckpointStateError) -> None:
    assert (str(error), repr(error), error.args) == (
        "checkpoint_failure",
        "CheckpointStateError('checkpoint_failure')",
        ("checkpoint_failure",),
    )
    assert error.__cause__ is None and error.__context__ is None


def _start(tmp_path):
    result = _register_checkpoint_run(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )
    assert isinstance(result, _RunActivated)
    return result


def _checkpoint_rows(workspace_path):
    with workspace_module._open_locked_checkpoint_workspace(workspace_path) as workspace:
        return workspace._mutate(
            lambda transaction: (
                transaction._fetchall("SELECT * FROM crawl_runs ORDER BY run_id"),
                transaction._fetchall("SELECT * FROM include_roots ORDER BY run_id,include_root_ordinal"),
                transaction._fetchall("SELECT * FROM root_progress ORDER BY run_id,include_root_ordinal"),
                transaction._fetchall("SELECT * FROM crawl_sessions ORDER BY session_id"),
            )
        )


def test_start_persists_canonical_first_state_and_conflict_is_a_tag(tmp_path) -> None:
    result = _register_checkpoint_run(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )
    assert isinstance(result, _RunActivated)
    assert result.snapshot.include_roots.root_ids == ("a", "b")
    assert result.snapshot.root_progress[0].value == "root_pending"
    assert result.session_id.value == "123e4567-e89b-42d3-a456-426614174001"

    conflict = _register_checkpoint_run(_request(tmp_path, StartNewRun()))
    assert conflict == _RunRegistryFailure(
        _RunRegistryFailureCategory.INCOMPLETE_RUN_CONFLICT
    )


def test_invalid_operation_and_fresh_resume_do_not_initialize_workspace(tmp_path) -> None:
    invalid = _register_checkpoint_run(_request(tmp_path, None))
    assert invalid == _RunRegistryFailure(
        _RunRegistryFailureCategory.RUN_OPERATION_INVALID
    )
    assert not (tmp_path / workspace_module.DB_NAME).exists()
    assert not (tmp_path / workspace_module.LOCK_NAME).exists()

    missing = _register_checkpoint_run(_request(tmp_path, ResumeUniqueIncompleteRun()))
    assert missing == _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_FOUND)
    assert not (tmp_path / workspace_module.DB_NAME).exists()
    assert (tmp_path / workspace_module.LOCK_NAME).exists()


def test_fresh_resume_reports_lock_contention_before_missing_database(tmp_path) -> None:
    lock_path = tmp_path / workspace_module.LOCK_NAME
    with lock_path.open("w+b") as lock_handle:
        workspace_module.portalocker.lock(
            lock_handle,
            workspace_module.portalocker.LOCK_EX | workspace_module.portalocker.LOCK_NB,
        )
        try:
            with pytest.raises(CheckpointStateError) as caught:
                with _register_checkpoint_run_context(
                    _request(tmp_path, ResumeUniqueIncompleteRun())
                ):
                    raise AssertionError("contention must not yield an outcome")
            _assert_sanitized(caught.value)
        finally:
            workspace_module.portalocker.unlock(lock_handle)
    assert not (tmp_path / workspace_module.DB_NAME).exists()


def test_resume_interrupts_only_the_prior_active_session(tmp_path) -> None:
    started = _register_checkpoint_run(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )
    assert isinstance(started, _RunActivated)

    resumed = _register_checkpoint_run(
        _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
        uuid4=_ids("123e4567-e89b-42d3-a456-426614174002"),
        utc_now=_clock,
    )
    assert isinstance(resumed, _RunActivated)

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        sessions = workspace._mutate(
            lambda transaction: transaction._fetchall(
                "SELECT status,ended_at,outcome_status,outcome_reason FROM crawl_sessions "
                "ORDER BY session_id"
            )
        )
    assert sessions == [
        ("interrupted", "2026-08-01T01:02:03.456Z", "interrupted", "process_interrupted"),
        ("active", None, None, None),
    ]


def test_resume_rejects_a_non_uuid_durable_session_id_without_repair(tmp_path) -> None:
    started = _register_checkpoint_run(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )
    assert isinstance(started, _RunActivated)

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(
                "UPDATE crawl_sessions SET session_id='legacy-session' "
                "WHERE run_id=?",
                (started.snapshot.run_id.value,),
            )
        )

    with pytest.raises(CheckpointStateError):
        _register_checkpoint_run(
            _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
            uuid4=_ids("123e4567-e89b-42d3-a456-426614174002"),
            utc_now=_clock,
        )

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        sessions = workspace._mutate(
            lambda transaction: transaction._fetchall(
                "SELECT session_id,status,ended_at FROM crawl_sessions"
            )
        )
    assert sessions == [("legacy-session", "active", None)]


def test_inventory_complete_resume_does_not_create_a_session(tmp_path) -> None:
    with _register_checkpoint_run_context(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    ) as started:
        assert isinstance(started, _RunActivated)
        roots = started.snapshot.include_roots
        for work in iter(started.load_next_inventory_work, None):
            assert work is not None and work.kind == "root"
            root_metadata = ConfluencePageMetadata(
                work.include_root_page_id,
                work.include_root_page_id,
                "SPACE",
            )
            started.commit_root_occurrence(
                InventoryRootCommit(
                    started.snapshot.run_id,
                    work.include_root_ordinal,
                    work.include_root_page_id,
                    root_metadata,
                    roots,
                )
            )
            window_work = started.load_next_inventory_work()
            assert window_work is not None and window_work.kind == "window"
            window = ConfluenceInventoryWindow((), window_work.next_start, 50, 0, 0)
            started.commit_inventory_window(
                InventoryWindowCommit(
                    started.snapshot.run_id,
                    window_work.include_root_ordinal,
                    window_work.include_root_page_id,
                    window_work.next_start,
                    window,
                    (),
                    roots,
                )
            )

    with _register_checkpoint_run_context(
        _request(tmp_path, ResumeUniqueIncompleteRun()),
        uuid4=_ids("123e4567-e89b-42d3-a456-426614174002"),
        utc_now=_clock,
    ) as result:
        assert isinstance(result, _InventoryComplete)
        with workspace_module._open_locked_checkpoint_workspace(tmp_path):
            pass


def test_start_conflicts_on_same_fingerprint_even_when_durable_roots_differ(tmp_path) -> None:
    started = _start(tmp_path)

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(
                "UPDATE include_roots SET include_root_page_id=? "
                "WHERE run_id=? AND include_root_ordinal=?",
                ("c", started.snapshot.run_id.value, 0),
            )
        )
        workspace._mutate(
            lambda transaction: transaction._execute(
                "UPDATE include_roots SET include_root_page_id=? "
                "WHERE run_id=? AND include_root_ordinal=?",
                ("d", started.snapshot.run_id.value, 1),
            )
        )

    result = _register_checkpoint_run(_request(tmp_path, StartNewRun()))
    assert result == _RunRegistryFailure(
        _RunRegistryFailureCategory.INCOMPLETE_RUN_CONFLICT
    )


def test_explicit_resume_returns_not_resumable_for_fingerprint_or_root_mismatch(tmp_path) -> None:
    started = _start(tmp_path)
    fingerprint_mismatch = _register_checkpoint_run(
        _request(
            tmp_path,
            ResumeExplicitRunId(started.snapshot.run_id),
            endpoint_url="https://other.invalid/confluence",
        )
    )
    assert fingerprint_mismatch == _RunRegistryFailure(
        _RunRegistryFailureCategory.RUN_NOT_RESUMABLE
    )

    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(
            lambda transaction: transaction._execute(
                "UPDATE include_roots SET include_root_page_id=CASE "
                "include_root_ordinal WHEN 0 THEN 'q-1' WHEN 1 THEN 'q-2' END "
                "WHERE run_id=?",
                (started.snapshot.run_id.value,),
            )
        )
    root_mismatch = _register_checkpoint_run(
        _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id))
    )
    assert root_mismatch == _RunRegistryFailure(
        _RunRegistryFailureCategory.RUN_NOT_RESUMABLE
    )


def test_unique_resume_reports_ambiguous_matching_runs_without_mutation(tmp_path) -> None:
    started = _start(tmp_path)
    second_run = "223e4567-e89b-42d3-a456-426614174000"
    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        def duplicate(transaction):
            transaction._execute(
                "INSERT INTO crawl_runs "
                "(run_id,generation_id,fingerprint_digest,status,inventory_phase,created_at) "
                "SELECT ?,?,fingerprint_digest,'incomplete','pending',created_at "
                "FROM crawl_runs WHERE run_id=?",
                (second_run, second_run, started.snapshot.run_id.value),
            )
            for ordinal, root_id in started.snapshot.include_roots.ordinals:
                transaction._execute(
                    "INSERT INTO include_roots "
                    "(run_id,include_root_ordinal,include_root_page_id) VALUES (?,?,?)",
                    (second_run, ordinal, root_id),
                )
                transaction._execute(
                    "INSERT INTO root_progress "
                    "(run_id,include_root_ordinal,progress,next_start,descendants_complete) "
                    "VALUES (?,?,'root_pending',NULL,0)",
                    (second_run, ordinal),
                )
        workspace._mutate(duplicate)

    before = _checkpoint_rows(tmp_path)
    with _register_checkpoint_run_context(
        _request(tmp_path, ResumeUniqueIncompleteRun())
    ) as result:
        assert result == _RunRegistryFailure(
            _RunRegistryFailureCategory.RUN_MATCH_AMBIGUOUS
        )
        with workspace_module._open_locked_checkpoint_workspace(tmp_path):
            pass
    assert _checkpoint_rows(tmp_path) == before


def test_root_cap_fails_before_workspace_or_providers(tmp_path) -> None:
    request = _request(
        tmp_path,
        StartNewRun(),
        root_ids=tuple(f"root-{index}" for index in range(17)),
    )
    calls = []

    def unexpected_uuid():
        calls.append("uuid")
        raise AssertionError("UUID provider must not run")

    def unexpected_clock():
        calls.append("clock")
        raise AssertionError("clock provider must not run")

    with pytest.raises(ValueError):
        _register_checkpoint_run(request, uuid4=unexpected_uuid, utc_now=unexpected_clock)
    assert calls == []
    assert not (tmp_path / workspace_module.DB_NAME).exists()
    assert not (tmp_path / workspace_module.LOCK_NAME).exists()


def test_uuid_and_clock_providers_run_only_for_successful_activations(tmp_path) -> None:
    start_calls = []

    def start_uuid():
        start_calls.append("uuid")
        return uuid.UUID(
            (
                "923e4567-e89b-42d3-a456-426614174000"
                if len(start_calls) == 1
                else "923e4567-e89b-42d3-a456-426614174001"
            )
        )

    def start_clock():
        start_calls.append("clock")
        return _clock()

    with _register_checkpoint_run_context(
        _request(tmp_path, StartNewRun()), uuid4=start_uuid, utc_now=start_clock
    ) as started:
        assert isinstance(started, _RunActivated)
    assert start_calls == ["uuid", "uuid", "clock"]

    resume_calls = []

    def resume_uuid():
        resume_calls.append("uuid")
        return uuid.UUID("923e4567-e89b-42d3-a456-426614174002")

    def resume_clock():
        resume_calls.append("clock")
        return _clock()

    with _register_checkpoint_run_context(
        _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
        uuid4=resume_uuid,
        utc_now=resume_clock,
    ) as resumed:
        assert isinstance(resumed, _RunActivated)
    assert resume_calls == ["uuid", "clock"]

    unexpected_calls = []

    def unexpected_provider():
        unexpected_calls.append("called")
        raise AssertionError("provider must not run")

    with _register_checkpoint_run_context(
        _request(tmp_path, StartNewRun()),
        uuid4=unexpected_provider,
        utc_now=unexpected_provider,
    ) as conflict:
        assert conflict == _RunRegistryFailure(
            _RunRegistryFailureCategory.INCOMPLETE_RUN_CONFLICT
        )
    assert unexpected_calls == []


def test_effective_input_snapshot_is_not_reread_after_open(tmp_path, monkeypatch) -> None:
    request = _request(tmp_path, StartNewRun())
    original_open = registry_module._open_locked_checkpoint_workspace

    @contextmanager
    def mutate_after_snapshot(workspace, **kwargs):
        object.__setattr__(request.source_config, "include_roots", (ConfluenceIncludeRoot("z"),))
        request.reliability_profile["inventory_page_size"] = 1
        with original_open(workspace, **kwargs) as capability:
            yield capability

    monkeypatch.setattr(registry_module, "_open_locked_checkpoint_workspace", mutate_after_snapshot)
    result = _register_checkpoint_run(
        request,
        uuid4=_ids(
            "323e4567-e89b-42d3-a456-426614174000",
            "323e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    )
    assert isinstance(result, _RunActivated)
    assert result.snapshot.include_roots.root_ids == ("a", "b")


@pytest.mark.parametrize("fault_prefix", ("UPDATE crawl_sessions", "INSERT INTO crawl_sessions"))
def test_resume_session_faults_roll_back_all_lifecycle_changes(
    tmp_path, monkeypatch, fault_prefix
) -> None:
    started = _start(tmp_path)
    before = _checkpoint_rows(tmp_path)
    original_execute = workspace_module._PrivateCheckpointTransaction._execute

    def fail_after_execute(transaction, sql, parameters=()):
        original_execute(transaction, sql, parameters)
        if sql.startswith(fault_prefix):
            raise RuntimeError("injected lifecycle fault")

    monkeypatch.setattr(
        workspace_module._PrivateCheckpointTransaction, "_execute", fail_after_execute
    )
    with pytest.raises(CheckpointStateError):
        _register_checkpoint_run(
            _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
            uuid4=_ids("423e4567-e89b-42d3-a456-426614174002"),
            utc_now=_clock,
        )
    assert _checkpoint_rows(tmp_path) == before


def test_generated_run_id_collision_is_sanitized_and_does_not_partial_commit(tmp_path) -> None:
    started = _start(tmp_path)
    before = _checkpoint_rows(tmp_path)
    with pytest.raises(CheckpointStateError):
        _register_checkpoint_run(
            _request(
                tmp_path,
                StartNewRun(),
                endpoint_url="https://collision.invalid/confluence",
            ),
            uuid4=_ids(started.snapshot.run_id.value),
            utc_now=_clock,
        )
    assert _checkpoint_rows(tmp_path) == before


def test_resume_commit_fault_rolls_back_the_interrupted_session(tmp_path, monkeypatch) -> None:
    started = _start(tmp_path)
    before = _checkpoint_rows(tmp_path)
    original_open = workspace_module._open_writable_connection

    class CommitFaultConnection:
        def __init__(self, connection):
            self._connection = connection

        def commit(self):
            raise RuntimeError("injected commit fault")

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        workspace_module,
        "_open_writable_connection",
        lambda path: CommitFaultConnection(original_open(path)),
    )
    monkeypatch.setattr(
        workspace_module,
        "_initialize_or_validate_connection",
        lambda _connection, **_kwargs: workspace_module.SCHEMA_VERSION,
    )
    with pytest.raises(CheckpointStateError):
        _register_checkpoint_run(
            _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
            uuid4=_ids("523e4567-e89b-42d3-a456-426614174002"),
            utc_now=_clock,
        )
    monkeypatch.undo()
    assert _checkpoint_rows(tmp_path) == before


@pytest.mark.parametrize(
    "mutation",
    (
        lambda run_id: ("UPDATE crawl_runs SET fingerprint_digest='bad' WHERE run_id=?", (run_id,)),
        lambda run_id: ("UPDATE crawl_runs SET created_at='not-a-timestamp' WHERE run_id=?", (run_id,)),
        lambda run_id: ("UPDATE include_roots SET include_root_page_id='z' WHERE run_id=? AND include_root_ordinal=0", (run_id,)),
        lambda run_id: ("UPDATE root_progress SET descendants_complete=1 WHERE run_id=? AND include_root_ordinal=0", (run_id,)),
    ),
)
def test_malformed_durable_rows_raise_without_repair(tmp_path, mutation) -> None:
    started = _start(tmp_path)
    before = _checkpoint_rows(tmp_path)
    sql, parameters = mutation(started.snapshot.run_id.value)
    with workspace_module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        workspace._mutate(lambda transaction: transaction._execute(sql, parameters))
    malformed = _checkpoint_rows(tmp_path)

    with pytest.raises(CheckpointStateError):
        _register_checkpoint_run(
            _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
            uuid4=_ids("523e4567-e89b-42d3-a456-426614174002"),
            utc_now=_clock,
        )
    assert _checkpoint_rows(tmp_path) == malformed


def test_activation_scope_retains_lock_and_exposes_only_metadata_and_invalidation(tmp_path) -> None:
    activation = None
    with _register_checkpoint_run_context(
        _request(tmp_path, StartNewRun()),
        uuid4=_ids(
            "623e4567-e89b-42d3-a456-426614174000",
            "623e4567-e89b-42d3-a456-426614174001",
        ),
        utc_now=_clock,
    ) as activation:
        assert isinstance(activation, _RunActivated)
        assert "_ACTIVE_WORKSPACES" not in vars(registry_module)
        assert repr(activation) == "_RunActivated()"
        assert not hasattr(activation, "_capability")
        assert not hasattr(activation, "_mutate")
        assert not any(
            forbidden in dir(activation)
            for forbidden in ("workspace", "connection", "path", "lock", "transaction", "sql")
        )
        assert {
            name for name in dir(activation) if not name.startswith("_")
        } <= {
            "session_id",
            "snapshot",
            "read_schema_state",
            "check_outbound_attempt",
            "reserve_outbound_attempt",
            "load_next_inventory_work",
            "commit_root_occurrence",
            "commit_inventory_window",
                "stream_inventory_occurrences",
                "complete_session",
                "pause_session",
            }
        with pytest.raises(CheckpointStateError) as caught:
            with workspace_module._open_locked_checkpoint_workspace(tmp_path):
                pass
        _assert_sanitized(caught.value)
        activation._invalidate()

    assert activation is not None
    activation._invalidate()
    with workspace_module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_activation_scope_propagates_caller_error_and_releases_lock(tmp_path) -> None:
    class CallerFailure(Exception):
        pass

    retained = None
    with pytest.raises(CallerFailure):
        with _register_checkpoint_run_context(
            _request(tmp_path, StartNewRun()),
            uuid4=_ids(
                "723e4567-e89b-42d3-a456-426614174000",
                "723e4567-e89b-42d3-a456-426614174001",
            ),
            utc_now=_clock,
        ) as activation:
            retained = activation
            raise CallerFailure("caller failure")
    assert retained is not None
    retained._invalidate()
    with workspace_module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_caller_checkpoint_error_with_opening_marker_is_not_rewritten(tmp_path) -> None:
    caller_error = CheckpointStateError()
    setattr(caller_error, "_missing_initial_database", True)
    with pytest.raises(CheckpointStateError) as caught:
        with _register_checkpoint_run_context(
            _request(tmp_path, StartNewRun()),
            uuid4=_ids(
                "753e4567-e89b-42d3-a456-426614174000",
                "753e4567-e89b-42d3-a456-426614174001",
            ),
            utc_now=_clock,
        ):
            raise caller_error
    assert caught.value is caller_error


def test_noop_outcomes_release_lock_before_their_context_body(tmp_path) -> None:
    with _register_checkpoint_run_context(
        _request(tmp_path, ResumeUniqueIncompleteRun())
    ) as missing:
        assert missing == _RunRegistryFailure(_RunRegistryFailureCategory.RUN_NOT_FOUND)
        with workspace_module._open_locked_checkpoint_workspace(tmp_path):
            pass

    _start(tmp_path)
    with _register_checkpoint_run_context(_request(tmp_path, StartNewRun())) as conflict:
        assert conflict == _RunRegistryFailure(
            _RunRegistryFailureCategory.INCOMPLETE_RUN_CONFLICT
        )
        with workspace_module._open_locked_checkpoint_workspace(tmp_path):
            pass


def test_activation_context_blocks_a_real_child_process_then_allows_resume(tmp_path) -> None:
    started = _start(tmp_path)
    child = """
import sys
from pathlib import Path
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId, ResumeExplicitRunId
from knowledgenexus.foundation.domain.models.confluence_source_config import ConfluenceIncludeRoot, ConfluenceSourceConfig
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import _RunRegistryRequest, _register_checkpoint_run
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import CheckpointStateError
workspace, run_id = sys.argv[1:]
profile = %r
request = _RunRegistryRequest(Path(workspace), ResumeExplicitRunId(CrawlRunId(run_id)), 'https://example.invalid/confluence', ConfluenceSourceConfig('source', 'SPACE', (ConfluenceIncludeRoot('b'), ConfluenceIncludeRoot('a'))), profile)
try:
    with _register_checkpoint_run(request):
        pass
except CheckpointStateError:
    raise SystemExit(2)
""" % PROFILE

    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[4] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    with _register_checkpoint_run_context(
        _request(tmp_path, ResumeExplicitRunId(started.snapshot.run_id)),
        uuid4=_ids("823e4567-e89b-42d3-a456-426614174002"),
        utc_now=_clock,
    ) as resumed:
        assert isinstance(resumed, _RunActivated)
        blocked = subprocess.run(
            [sys.executable, "-c", child, str(tmp_path), resumed.snapshot.run_id.value],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=5,
        )
        assert blocked.returncode == 2, blocked.stderr

    allowed = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), started.snapshot.run_id.value],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=5,
    )
    assert allowed.returncode == 0, allowed.stderr
    sessions = _checkpoint_rows(tmp_path)[3]
    assert [row[2] for row in sessions].count("interrupted") == 2
    assert [row[2] for row in sessions].count("active") == 1
