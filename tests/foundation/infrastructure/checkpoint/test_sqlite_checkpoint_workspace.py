from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlSessionId
from knowledgenexus.foundation.infrastructure.checkpoint import sqlite_checkpoint_workspace as module
from knowledgenexus.foundation.ports import CheckpointStateError


# Keep the v1 session catalog expectation independent from implementation
# constants so a coordinated implementation/validator drift is observable.
_CRAWL_SESSIONS_DDL = (
    "CREATE TABLE crawl_sessions (session_id TEXT PRIMARY KEY NOT NULL CHECK (length(session_id) > 0), "
    "run_id TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN "
    "('active','completed','interrupted','paused')), started_at TEXT NOT NULL CHECK "
    "(length(started_at) = 24 AND COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ', "
    "started_at) = started_at, 0)), ended_at TEXT CHECK (ended_at IS NULL OR "
    "(length(ended_at) = 24 AND COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ', "
    "ended_at) = ended_at, 0))), outcome_status TEXT, outcome_reason TEXT, CHECK "
    "(COALESCE((status = 'active' AND ended_at IS NULL AND outcome_status IS NULL "
    "AND outcome_reason IS NULL) OR (status = 'completed' AND ended_at IS NOT NULL "
    "AND outcome_status = 'completed' AND outcome_reason = 'completed') OR (status "
    "= 'interrupted' AND ended_at IS NOT NULL AND outcome_status = 'interrupted' "
    "AND outcome_reason = 'process_interrupted') OR (status = 'paused' AND ended_at "
    "IS NOT NULL AND outcome_status = 'paused' AND outcome_reason = "
    "'controlled_checkpoint_stop'), 0)), FOREIGN KEY (run_id) REFERENCES "
    "crawl_runs(run_id))"
)
_CRAWL_SESSIONS_RUN_STARTED_INDEX_DDL = (
    "CREATE INDEX idx_crawl_sessions_run_started ON crawl_sessions(run_id, started_at)"
)
_CRAWL_SESSIONS_ONE_ACTIVE_INDEX_DDL = (
    "CREATE UNIQUE INDEX idx_crawl_sessions_one_active ON crawl_sessions(run_id) "
    "WHERE status = 'active'"
)
_CRAWL_SESSIONS_TABLE_LAYOUT = (
    ("session_id", "TEXT", 1, 1),
    ("run_id", "TEXT", 1, 0),
    ("status", "TEXT", 1, 0),
    ("started_at", "TEXT", 1, 0),
    ("ended_at", "TEXT", 0, 0),
    ("outcome_status", "TEXT", 0, 0),
    ("outcome_reason", "TEXT", 0, 0),
)
_CRAWL_SESSIONS_FOREIGN_KEY_LAYOUT = (
    (0, 0, "crawl_runs", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"),
)
_CRAWL_SESSIONS_INDEX_LAYOUT = (
    (0, "idx_crawl_sessions_one_active", 1, "c", 1),
    (1, "idx_crawl_sessions_run_started", 0, "c", 0),
    (2, "sqlite_autoindex_crawl_sessions_1", 1, "pk", 0),
)
_CRAWL_SESSIONS_INDEX_XINFO = {
    "idx_crawl_sessions_one_active": (
        (0, 1, "run_id", 0, "BINARY", 1),
        (1, -1, None, 0, "BINARY", 0),
    ),
    "idx_crawl_sessions_run_started": (
        (0, 1, "run_id", 0, "BINARY", 1),
        (1, 3, "started_at", 0, "BINARY", 1),
        (2, -1, None, 0, "BINARY", 0),
    ),
    "sqlite_autoindex_crawl_sessions_1": (
        (0, 0, "session_id", 0, "BINARY", 1),
        (1, -1, None, 0, "BINARY", 0),
    ),
}
_EXPECTED_CATALOG_OBJECTS = {
    ("checkpoint_metadata", "table"),
    ("crawl_runs", "table"),
    ("crawl_sessions", "table"),
    ("include_roots", "table"),
    ("root_occurrences", "table"),
    ("root_progress", "table"),
    ("inventory_windows", "table"),
    ("inventory_occurrences", "table"),
    ("checkpoint_transitions", "table"),
    ("request_budget_reservations", "table"),
    ("idx_crawl_sessions_run_started", "index"),
    ("idx_crawl_sessions_one_active", "index"),
    ("idx_inventory_occurrences_run_page", "index"),
    ("idx_inventory_windows_run_root", "index"),
    ("idx_root_progress_incomplete", "index"),
}
_PRE_CORRECTION_V1_DDL = (
    "CREATE TABLE checkpoint_metadata (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), schema_identity TEXT NOT NULL CHECK (schema_identity = 'knowledgenexus.m7.checkpoint.v1'), schema_version INTEGER NOT NULL CHECK (schema_version = 1))",
    "CREATE TABLE crawl_runs (run_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL UNIQUE, fingerprint_digest TEXT NOT NULL CHECK (length(fingerprint_digest) > 0), status TEXT NOT NULL CHECK (status IN ('incomplete','complete')), inventory_phase TEXT NOT NULL CHECK (inventory_phase IN ('pending','complete')), created_at TEXT NOT NULL)",
    "CREATE TABLE include_roots (run_id TEXT NOT NULL, include_root_ordinal INTEGER NOT NULL CHECK (include_root_ordinal >= 0), include_root_page_id TEXT NOT NULL CHECK (length(include_root_page_id) > 0), PRIMARY KEY (run_id, include_root_ordinal), UNIQUE (run_id, include_root_page_id), FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id))",
    "CREATE TABLE root_occurrences (run_id TEXT NOT NULL, include_root_ordinal INTEGER NOT NULL, page_id TEXT NOT NULL CHECK (length(page_id) > 0), title TEXT NOT NULL CHECK (length(title) > 0), space_key TEXT NOT NULL CHECK (length(space_key) > 0), parent_page_id TEXT, updated_at TEXT, source_version TEXT, ancestor_page_ids_json TEXT NOT NULL, ancestor_titles_json TEXT NOT NULL, labels_json TEXT NOT NULL, attachment_count INTEGER CHECK (attachment_count IS NULL OR attachment_count >= 0), PRIMARY KEY (run_id, include_root_ordinal), FOREIGN KEY (run_id, include_root_ordinal) REFERENCES include_roots(run_id, include_root_ordinal))",
    "CREATE TABLE root_progress (run_id TEXT NOT NULL, include_root_ordinal INTEGER NOT NULL, progress TEXT NOT NULL CHECK (progress IN ('root_pending','root_committed','descendants_pending','descendants_complete')), next_start INTEGER CHECK (next_start IS NULL OR next_start >= 0), descendants_complete INTEGER NOT NULL CHECK (descendants_complete IN (0,1)), PRIMARY KEY (run_id, include_root_ordinal), FOREIGN KEY (run_id, include_root_ordinal) REFERENCES include_roots(run_id, include_root_ordinal))",
    "CREATE TABLE inventory_windows (run_id TEXT NOT NULL, include_root_ordinal INTEGER NOT NULL, requested_start INTEGER NOT NULL CHECK (requested_start >= 0), observed_start INTEGER NOT NULL CHECK (observed_start >= 0), response_size INTEGER NOT NULL CHECK (response_size >= 0), total_size INTEGER NOT NULL CHECK (total_size >= 0), next_start INTEGER NOT NULL CHECK (next_start >= 0), terminal INTEGER NOT NULL CHECK (terminal IN (0,1)), PRIMARY KEY (run_id, include_root_ordinal, requested_start), FOREIGN KEY (run_id, include_root_ordinal) REFERENCES include_roots(run_id, include_root_ordinal))",
    "CREATE TABLE inventory_occurrences (run_id TEXT NOT NULL, include_root_ordinal INTEGER NOT NULL, window_start INTEGER NOT NULL CHECK (window_start >= 0), item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 0), page_id TEXT NOT NULL CHECK (length(page_id) > 0), title TEXT NOT NULL CHECK (length(title) > 0), space_key TEXT NOT NULL CHECK (length(space_key) > 0), parent_page_id TEXT, updated_at TEXT, source_version TEXT, ancestor_page_ids_json TEXT NOT NULL, ancestor_titles_json TEXT NOT NULL, labels_json TEXT NOT NULL, attachment_count INTEGER CHECK (attachment_count IS NULL OR attachment_count >= 0), PRIMARY KEY (run_id, include_root_ordinal, window_start, item_ordinal), FOREIGN KEY (run_id, include_root_ordinal, window_start) REFERENCES inventory_windows(run_id, include_root_ordinal, requested_start))",
    "CREATE TABLE checkpoint_transitions (run_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence >= 0), include_root_ordinal INTEGER NOT NULL, from_progress TEXT NOT NULL CHECK (from_progress IN ('root_pending','root_committed','descendants_pending','descendants_complete')), to_progress TEXT NOT NULL CHECK (to_progress IN ('root_pending','root_committed','descendants_pending','descendants_complete')), PRIMARY KEY (run_id, sequence), FOREIGN KEY (run_id, include_root_ordinal) REFERENCES include_roots(run_id, include_root_ordinal))",
    "CREATE TABLE request_budget_reservations (run_id TEXT NOT NULL, reservation_sequence INTEGER NOT NULL CHECK (reservation_sequence >= 0), reserved_at TEXT NOT NULL, PRIMARY KEY (run_id, reservation_sequence), FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id))",
    "CREATE INDEX idx_inventory_occurrences_run_page ON inventory_occurrences(run_id, page_id)",
    "CREATE INDEX idx_inventory_windows_run_root ON inventory_windows(run_id, include_root_ordinal, requested_start)",
    "CREATE INDEX idx_root_progress_incomplete ON root_progress(run_id, descendants_complete, include_root_ordinal)",
)


def _assert_durability_pragmas(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert conn.execute("PRAGMA busy_timeout").fetchone() == (0,)
    assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert conn.execute("PRAGMA synchronous").fetchone() == (3,)


def test_fresh_and_reopen(tmp_path) -> None:
    with sqlite3.connect(tmp_path / module.DB_NAME) as conn:
        assert module._initialize_or_validate_connection(conn, initialize=True) == 1
        _assert_durability_pragmas(conn)
    with sqlite3.connect(tmp_path / module.DB_NAME) as conn:
        assert module._initialize_or_validate_connection(conn, initialize=False) == 1
        _assert_durability_pragmas(conn)
    with sqlite3.connect(tmp_path / module.DB_NAME) as conn:
        assert conn.execute("PRAGMA application_id").fetchone()[0] == module.APPLICATION_ID
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 10
        assert set(
            conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        ) == _EXPECTED_CATALOG_OBJECTS
        catalog_sql = dict(
            conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE name IN "
                "('crawl_sessions', 'idx_crawl_sessions_run_started', "
                "'idx_crawl_sessions_one_active')"
            )
        )
        assert catalog_sql == {
            "crawl_sessions": _CRAWL_SESSIONS_DDL,
            "idx_crawl_sessions_run_started": _CRAWL_SESSIONS_RUN_STARTED_INDEX_DDL,
            "idx_crawl_sessions_one_active": _CRAWL_SESSIONS_ONE_ACTIVE_INDEX_DDL,
        }
        assert tuple(
            (row[1], row[2].upper(), row[3], row[5])
            for row in conn.execute("PRAGMA table_info(crawl_sessions)")
        ) == _CRAWL_SESSIONS_TABLE_LAYOUT
        assert tuple(
            tuple(row[:8]) for row in conn.execute("PRAGMA foreign_key_list(crawl_sessions)")
        ) == _CRAWL_SESSIONS_FOREIGN_KEY_LAYOUT
        assert tuple(
            tuple(row[:5]) for row in conn.execute("PRAGMA index_list(crawl_sessions)")
        ) == _CRAWL_SESSIONS_INDEX_LAYOUT
        for name, expected_layout in _CRAWL_SESSIONS_INDEX_XINFO.items():
            assert tuple(
                tuple(row[:6]) for row in conn.execute(f"PRAGMA index_xinfo({name})")
            ) == expected_layout
        assert module._normalized_sql(catalog_sql["idx_crawl_sessions_one_active"]) == (
            "CREATE UNIQUE INDEX idx_crawl_sessions_one_active ON crawl_sessions(run_id) "
            "WHERE status = 'active'"
        )
    assert module._preflight(tmp_path / module.DB_NAME).absent is False


def _assert_sanitized(error: CheckpointStateError) -> None:
    assert (str(error), repr(error), error.args) == (
        "checkpoint_failure",
        "CheckpointStateError('checkpoint_failure')",
        ("checkpoint_failure",),
    )
    assert error.__cause__ is None and error.__context__ is None


def test_locked_workspace_initializes_reopens_and_preserves_lock_bytes(tmp_path) -> None:
    lock = tmp_path / module.LOCK_NAME
    lock.write_bytes(b"opaque pre-existing lock bytes")

    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        assert type(workspace) is module._LockedCheckpointWorkspace
        assert not hasattr(workspace, "connection")
        assert workspace._mutate(lambda transaction: transaction._fetchone("SELECT 1")) == (1,)

    assert lock.read_bytes() == b"opaque pre-existing lock bytes"
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass
    with sqlite3.connect(tmp_path / module.DB_NAME) as conn:
        module._initialize_or_validate_connection(conn, initialize=False)
        _assert_durability_pragmas(conn)


def test_locked_workspace_allows_unrelated_sibling_directory_lifecycle(tmp_path) -> None:
    sibling = tmp_path.parent / f"{tmp_path.name}-unrelated-sibling"
    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        sibling.mkdir()
        try:
            assert workspace._mutate(
                lambda transaction: transaction._fetchone("SELECT 1")
            ) == (1,)
        finally:
            sibling.rmdir()


def test_mutation_allows_sqlite_journal_lifecycle(tmp_path) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        def transient_schema(transaction):
            transaction._execute("CREATE TABLE transient_lifecycle(value INTEGER)")
            transaction._execute("DROP TABLE transient_lifecycle")

        workspace._mutate(transient_schema)


def test_locked_workspace_orders_lock_before_connect_and_uses_strict_open_modes(
    tmp_path, monkeypatch
) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass

    events = []
    real_lock = module.portalocker.lock
    real_connect = module.sqlite3.connect
    real_open = module.os.open

    def track_lock(handle, flags, *args, **kwargs):
        events.append(("lock", flags))
        return real_lock(handle, flags, *args, **kwargs)

    def track_connect(database, *args, **kwargs):
        events.append(("connect", database, kwargs.get("timeout")))
        return real_connect(database, *args, **kwargs)

    def track_open(path, flags, *args, **kwargs):
        events.append(("os.open", str(path), flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.portalocker, "lock", track_lock)
    monkeypatch.setattr(module.sqlite3, "connect", track_connect)
    monkeypatch.setattr(module.os, "open", track_open)

    with module._open_locked_checkpoint_workspace(tmp_path):
        pass
    fresh_workspace = tmp_path / "fresh-workspace"
    fresh_workspace.mkdir()
    with module._open_locked_checkpoint_workspace(fresh_workspace):
        pass

    first_connect = next(index for index, event in enumerate(events) if event[0] == "connect")
    lock_event = next(index for index, event in enumerate(events) if event[0] == "lock")
    assert lock_event < first_connect
    assert events[lock_event][1] == module.portalocker.LOCK_EX | module.portalocker.LOCK_NB
    connects = [event for event in events if event[0] == "connect"]
    assert all(event[2] == 0 for event in connects)
    assert any("mode=ro" in event[1] for event in connects)
    assert any("mode=rw" in event[1] for event in connects)
    db_claims = [
        event for event in events
        if event[0] == "os.open" and event[1].endswith(module.DB_NAME)
    ]
    assert db_claims and any(event[2] & module.os.O_EXCL for event in db_claims)


def test_locked_workspace_contends_nonblockingly_and_releases(tmp_path) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path):
        with pytest.raises(CheckpointStateError) as caught:
            with module._open_locked_checkpoint_workspace(tmp_path):
                pass
        _assert_sanitized(caught.value)
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_locked_workspace_invalidates_retained_private_seams(tmp_path) -> None:
    retained = {}

    def retain(transaction):
        retained["transaction"] = transaction
        transaction._execute("SELECT 1")

    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        retained["workspace"] = workspace
        retained["connection"] = workspace._connection
        workspace._mutate(retain)

    for callback in (
        lambda: retained["workspace"]._mutate(lambda transaction: None),
        lambda: retained["transaction"]._fetchone("SELECT 1"),
    ):
        with pytest.raises(CheckpointStateError) as caught:
            callback()
        _assert_sanitized(caught.value)
    with pytest.raises(sqlite3.ProgrammingError):
        retained["connection"].execute("SELECT 1")


def test_locked_workspace_rejects_lock_identity_replacement_and_rolls_back(
    tmp_path, monkeypatch
) -> None:
    armed = False
    original_observe = module._observe_regular_entry
    lock = tmp_path / module.LOCK_NAME

    def observe(path):
        result = original_observe(path)
        if armed and path == lock and not result.absent:
            return module._EntryObservation(False, (result.identity[0], result.identity[1] + 1))
        return result

    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        connection = workspace._connection
        monkeypatch.setattr(module, "_observe_regular_entry", observe)

        def operation(transaction):
            nonlocal armed
            transaction._execute("CREATE TABLE should_rollback(value INTEGER)")
            armed = True

        with pytest.raises(CheckpointStateError) as caught:
            workspace._mutate(operation)
        _assert_sanitized(caught.value)
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    monkeypatch.undo()
    with module._open_locked_checkpoint_workspace(tmp_path) as reopened:
        assert reopened._connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='should_rollback'"
        ).fetchone() == (0,)


def test_locked_workspace_sanitizes_callback_failure_and_releases_resources(tmp_path) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        with pytest.raises(CheckpointStateError) as caught:
            workspace._mutate(
                lambda _transaction: (_ for _ in ()).throw(
                    RuntimeError("secret callback failure")
                )
            )
        _assert_sanitized(caught.value)
        with pytest.raises(CheckpointStateError) as stale:
            workspace._mutate(lambda _transaction: None)
        _assert_sanitized(stale.value)

    with module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_locked_workspace_rejects_database_identity_replacement_before_mutation(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / module.DB_NAME
    original_observe = module._observe_database
    armed = False

    def observe(path):
        result = original_observe(path)
        if armed and path == database and not result.absent:
            return module._DatabaseObservation(
                False,
                (result.identity[0], result.identity[1] + 1, *result.identity[2:]),
            )
        return result

    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        connection = workspace._connection
        monkeypatch.setattr(module, "_observe_database", observe)
        armed = True
        with pytest.raises(CheckpointStateError) as caught:
            workspace._mutate(lambda _transaction: pytest.fail("must not execute"))
        _assert_sanitized(caught.value)
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    monkeypatch.undo()
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_locked_workspace_rejects_same_inode_database_metadata_tamper_before_mutation(
    tmp_path,
) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path) as workspace:
        database = tmp_path / module.DB_NAME
        info = database.stat()
        os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with pytest.raises(CheckpointStateError) as caught:
            workspace._mutate(lambda _transaction: pytest.fail("must not execute"))
        _assert_sanitized(caught.value)


def test_locked_workspace_rejects_database_replacement_after_initialization(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / module.DB_NAME
    original_initialize = module._initialize_or_validate_connection
    original_observe = module._observe_database
    initialized = False

    def initialize(*args, **kwargs):
        nonlocal initialized
        result = original_initialize(*args, **kwargs)
        initialized = True
        return result

    def observe(path):
        result = original_observe(path)
        if initialized and path == database and not result.absent:
            return module._DatabaseObservation(
                False,
                (result.identity[0], result.identity[1] + 1, *result.identity[2:]),
            )
        return result

    monkeypatch.setattr(module, "_initialize_or_validate_connection", initialize)
    monkeypatch.setattr(module, "_observe_database", observe)
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)


@pytest.mark.parametrize("stage", ["open", "initialize"])
def test_locked_workspace_rejects_same_inode_database_change_after_preflight(
    tmp_path, monkeypatch, stage: str
) -> None:
    database = tmp_path / module.DB_NAME
    _valid_database(database)
    original_open = module._open_writable_connection
    original_initialize = module._initialize_or_validate_connection

    def alter_observation() -> None:
        info = database.stat()
        os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))

    def open_connection(path):
        connection = original_open(path)
        if stage == "open":
            alter_observation()
        return connection

    def initialize(*args, **kwargs):
        result = original_initialize(*args, **kwargs)
        if stage == "initialize":
            alter_observation()
        return result

    monkeypatch.setattr(module, "_open_writable_connection", open_connection)
    monkeypatch.setattr(module, "_initialize_or_validate_connection", initialize)
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)


def test_locked_workspace_lock_failure_on_fresh_workspace_creates_no_database(
    tmp_path, monkeypatch
) -> None:
    initialized = []

    def fail_lock(*args, **kwargs):
        raise RuntimeError("lock failure")

    monkeypatch.setattr(module.portalocker, "lock", fail_lock)
    monkeypatch.setattr(
        module,
        "_initialize_or_validate_connection",
        lambda *args, **kwargs: initialized.append((args, kwargs)),
    )
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)
    assert initialized == []
    assert not (tmp_path / module.DB_NAME).exists()


@pytest.mark.parametrize("failure", ["preflight", "open", "initialize", "unlock"])
def test_locked_workspace_post_lock_failures_release_for_reacquisition(
    tmp_path, monkeypatch, failure: str
) -> None:
    if failure in {"open", "initialize"}:
        _valid_database(tmp_path / module.DB_NAME)
    if failure == "preflight":
        def fail(_path):
            raise module._fail()
        monkeypatch.setattr(module, "_preflight", fail)
    elif failure == "open":
        def fail(_path):
            raise module._fail()
        monkeypatch.setattr(module, "_open_writable_connection", fail)
    elif failure == "initialize":
        def fail(*args, **kwargs):
            raise module._fail()
        monkeypatch.setattr(module, "_initialize_or_validate_connection", fail)
    else:
        real_unlock = module.portalocker.unlock
        monkeypatch.setattr(module.portalocker, "unlock", lambda _handle: (_ for _ in ()).throw(RuntimeError("unlock")))

    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)
    monkeypatch.undo()
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_locked_workspace_close_precedes_unlock(tmp_path, monkeypatch) -> None:
    _valid_database(tmp_path / module.DB_NAME)
    events = []
    real_connect = module.sqlite3.connect
    real_unlock = module.portalocker.unlock

    class TrackingConnection(sqlite3.Connection):
        def close(self):
            events.append("close")
            return super().close()

    def connect(*args, **kwargs):
        kwargs["factory"] = TrackingConnection
        return real_connect(*args, **kwargs)

    def unlock(handle):
        events.append("unlock")
        return real_unlock(handle)

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    monkeypatch.setattr(module, "_initialize_or_validate_connection", lambda *args, **kwargs: 1)
    monkeypatch.setattr(module.portalocker, "unlock", unlock)
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass
    assert events[-2:] == ["close", "unlock"]


def test_locked_workspace_connection_close_failure_is_sanitized_and_reacquirable(
    tmp_path, monkeypatch
) -> None:
    _valid_database(tmp_path / module.DB_NAME)
    real_connect = module.sqlite3.connect

    class BrokenClose(sqlite3.Connection):
        def close(self):
            super().close()
            raise RuntimeError("secret close failure")

    def connect(*args, **kwargs):
        kwargs["factory"] = BrokenClose
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)
    monkeypatch.undo()
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass


def test_locked_workspace_failed_fresh_initialization_preserves_unknown_database(
    tmp_path, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise module._fail()

    monkeypatch.setattr(module, "_initialize_or_validate_connection", fail)
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)
    db = tmp_path / module.DB_NAME
    assert db.exists() and db.read_bytes() == b""
    assert (tmp_path / module.LOCK_NAME).exists()
    monkeypatch.undo()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)


def test_locked_workspace_rejects_unknown_database_without_writing(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    db.write_bytes(b"not sqlite")
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    _assert_sanitized(caught.value)
    assert db.read_bytes() == before
    assert (tmp_path / module.LOCK_NAME).exists()


def test_locked_workspace_process_contention_and_abrupt_release(tmp_path) -> None:
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    lock = tmp_path / module.LOCK_NAME
    lock_bytes = b"opaque child lock bytes"
    lock.write_bytes(lock_bytes)
    lock_identity = (lock.lstat().st_dev, lock.lstat().st_ino)
    child = """
import os
import sys
import time
from pathlib import Path
from knowledgenexus.foundation.infrastructure.checkpoint import sqlite_checkpoint_workspace as module
workspace, ready, release, abrupt = map(Path, sys.argv[1:])
with module._open_locked_checkpoint_workspace(workspace):
    ready.write_text('ready', encoding='ascii')
    if abrupt.name == 'abrupt':
        os._exit(0)
    while not release.exists():
        time.sleep(0.01)
"""

    def start(abrupt: bool) -> subprocess.Popen:
        env = dict(os.environ)
        src = str(Path(__file__).resolve().parents[4] / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        marker = tmp_path / ("abrupt" if abrupt else "normal")
        return subprocess.Popen(
            [sys.executable, "-c", child, str(tmp_path), str(ready), str(release), str(marker)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    process = start(abrupt=False)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), process.communicate(timeout=5)
        with pytest.raises(CheckpointStateError):
            with module._open_locked_checkpoint_workspace(tmp_path):
                pass
        release.touch()
        assert process.wait(timeout=5) == 0
        assert lock.read_bytes() == lock_bytes
        assert (lock.lstat().st_dev, lock.lstat().st_ino) == lock_identity
    finally:
        if process.poll() is None:
            release.touch()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    ready.unlink()
    release.unlink()
    process = start(abrupt=True)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), process.communicate(timeout=5)
        assert process.wait(timeout=5) == 0
        assert lock.read_bytes() == lock_bytes
        assert (lock.lstat().st_dev, lock.lstat().st_ino) == lock_identity
        with module._open_locked_checkpoint_workspace(tmp_path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_locked_workspace_real_process_contender_is_bounded_and_recovers(tmp_path) -> None:
    ready = tmp_path / "holder-ready"
    release = tmp_path / "holder-release"
    result = tmp_path / "contender-result"
    holder_code = """
import sys
import time
from pathlib import Path
from knowledgenexus.foundation.infrastructure.checkpoint import sqlite_checkpoint_workspace as module
workspace, ready, release = map(Path, sys.argv[1:])
with module._open_locked_checkpoint_workspace(workspace):
    ready.touch()
    while not release.exists():
        time.sleep(0.01)
"""
    contender_code = """
import sys
from pathlib import Path
from knowledgenexus.foundation.infrastructure.checkpoint import sqlite_checkpoint_workspace as module
workspace, result = map(Path, sys.argv[1:])
try:
    with module._open_locked_checkpoint_workspace(workspace):
        result.write_text('acquired', encoding='ascii')
except Exception:
    result.write_text('failed', encoding='ascii')
"""
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[4] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(tmp_path), str(ready), str(release)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), holder.communicate(timeout=5)

        started = time.monotonic()
        contender = subprocess.run(
            [sys.executable, "-c", contender_code, str(tmp_path), str(result)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=3,
        )
        assert contender.returncode == 0
        assert result.read_text(encoding="ascii") == "failed"
        assert time.monotonic() - started < 2

        release.touch()
        assert holder.wait(timeout=5) == 0
        result.unlink()
        recovered = subprocess.run(
            [sys.executable, "-c", contender_code, str(tmp_path), str(result)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert recovered.returncode == 0
        assert result.read_text(encoding="ascii") == "acquired"
    finally:
        if holder.poll() is None:
            release.touch()
            try:
                holder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=5)


def test_existing_empty_database_fails_without_write(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    db.touch()
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError) as caught:
        module._preflight(db)
    assert str(caught.value) == "checkpoint_failure"
    assert db.read_bytes() == before


def test_initializer_requires_explicit_preflight_decision(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    for initialize in (None, False):
        conn = sqlite3.connect(db)
        with pytest.raises(CheckpointStateError) as caught:
            module._initialize_or_validate_connection(conn, initialize=initialize)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
        with sqlite3.connect(db) as verify:
            assert verify.execute(
                "SELECT count(*) FROM sqlite_master WHERE type IN ('table','index')"
            ).fetchone() == (0,)


def test_symlink_workspace_child_rejected(tmp_path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"x")
    link = tmp_path / module.DB_NAME
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(tmp_path)


@pytest.mark.parametrize("kind", ["relative", "traversal", "file"])
def test_workspace_admission_rejects_relative_traversal_and_file_paths(tmp_path, kind: str) -> None:
    if kind == "relative":
        workspace = Path("relative-workspace")
    elif kind == "traversal":
        workspace = tmp_path / ".." / tmp_path.name
    else:
        workspace = tmp_path / "workspace-file"
        workspace.write_bytes(b"not a directory")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(workspace)


@pytest.mark.parametrize("name", [module.LOCK_NAME, *module._SIDECARS])
def test_direct_lock_and_sidecar_symlinks_are_rejected(tmp_path, name: str) -> None:
    target = tmp_path / "symlink-target"
    target.write_bytes(b"x")
    link = tmp_path / name
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(tmp_path)


def test_public_port_and_checkpoint_package_exports_are_closed() -> None:
    import knowledgenexus.foundation.infrastructure.checkpoint as checkpoint_package
    import knowledgenexus.foundation.ports as ports

    assert {
        "CheckpointFailureCategory",
        "CheckpointSchemaState",
        "CheckpointStateError",
        "ConfluenceCheckpointStatePort",
    }.issubset(set(ports.__all__))
    for forbidden in (
        "sqlite3",
        "Path",
        "_initialize_or_validate_connection",
        "_preflight",
        "_guard_workspace",
    ):
        assert forbidden not in ports.__all__
        assert not hasattr(ports, forbidden)
    assert getattr(checkpoint_package, "__all__", []) == []
    for forbidden in (
        "SqliteCheckpointWorkspace",
        "open_checkpoint_workspace",
        "open",
        "connection",
    ):
        assert not hasattr(checkpoint_package, forbidden)


def test_c2_exposes_no_lease_or_workspace_opener() -> None:
    for symbol in (
        "_WriterLockLease",
        "_open_after_writer_lock",
        "_SqliteCheckpointWorkspace",
        "_require_current_writer_lock",
        "_C3_WRITER_LOCK_HANDOFF",
        "_lease_from_held_writer_lock",
    ):
        assert not hasattr(module, symbol)


def test_workspace_path_subclass_is_rejected_before_path_derivation(tmp_path) -> None:
    outside = tmp_path.parent / "outside"

    class RedirectingPath(type(tmp_path)):
        def __truediv__(self, child):
            return outside / child

    with pytest.raises(CheckpointStateError):
        module._guard_workspace(RedirectingPath(tmp_path))
    assert not outside.exists()


@pytest.mark.parametrize("name", [module.DB_NAME, module.LOCK_NAME, *module._SIDECARS])
def test_dangling_child_symlink_is_rejected(tmp_path, name: str) -> None:
    try:
        (tmp_path / name).symlink_to(tmp_path / "missing-target")
    except OSError:
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(tmp_path)


def test_workspace_symlink_is_rejected(tmp_path) -> None:
    target = tmp_path / "workspace-target"
    target.mkdir()
    workspace = tmp_path / "workspace-link"
    try:
        workspace.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(workspace)


def test_symlinked_existing_ancestor_is_rejected(tmp_path) -> None:
    target = tmp_path / "ancestor-target"
    workspace = target / "workspace"
    workspace.mkdir(parents=True)
    link = tmp_path / "ancestor-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink capability unavailable")
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(link / "workspace")


def test_windows_junction_workspace_is_rejected(tmp_path) -> None:
    if os.name != "nt" or not hasattr(os.path, "isjunction"):
        pytest.skip("Windows junction capability unavailable")
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction-workspace"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not os.path.isjunction(junction):
        pytest.skip("Windows junction creation unavailable")
    try:
        with pytest.raises(CheckpointStateError):
            module._guard_workspace(junction)
    finally:
        junction.rmdir()


@pytest.mark.parametrize("name", [module.DB_NAME, module.LOCK_NAME, *module._SIDECARS])
def test_directory_child_is_rejected(tmp_path, name: str) -> None:
    (tmp_path / name).mkdir()
    with pytest.raises(CheckpointStateError):
        module._guard_workspace(tmp_path)


def test_preflight_rejects_foreign_header_without_write(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA application_id=7")
        conn.commit()
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_secret_failure_does_not_retain_exception_context(tmp_path, monkeypatch) -> None:
    def fail(_connection) -> None:
        raise RuntimeError("secret-marker")

    monkeypatch.setattr(module, "_configure_connection", fail)
    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    with pytest.raises(CheckpointStateError) as caught:
        module._initialize_or_validate_connection(conn, initialize=True)
    error = caught.value
    assert (str(error), repr(error), error.args) == ("checkpoint_failure", "CheckpointStateError('checkpoint_failure')", ("checkpoint_failure",))
    assert error.__cause__ is None and error.__context__ is None
    assert "secret-marker" not in repr(error)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def _valid_database(path) -> None:
    with sqlite3.connect(path) as conn:
        module._initialize_or_validate_connection(conn, initialize=True)


def _new_session_id() -> str:
    session_id = str(uuid.uuid4())
    assert CrawlSessionId(session_id).value == session_id
    return session_id


def _insert_run(conn: sqlite3.Connection, run_id: str = "run") -> str:
    conn.execute(
        "INSERT INTO crawl_runs VALUES (?, ?, ?, 'incomplete', 'pending', ?)",
        (run_id, f"generation-{run_id}", "digest", "2026-08-01T00:00:00.000Z"),
    )
    return run_id


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str | None,
    run_id: str,
    status: str,
    started_at: str | None = "2026-08-01T00:00:00.000Z",
    ended_at: str | None = None,
    outcome_status: str | None = None,
    outcome_reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO crawl_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, run_id, status, started_at, ended_at, outcome_status, outcome_reason),
    )


def test_crawl_sessions_preserve_historical_terminal_sessions(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        _insert_run(conn)
        _insert_session(
            conn, _new_session_id(), "run", "completed",
            ended_at="2026-08-01T00:00:01.000Z",
            outcome_status="completed", outcome_reason="completed",
        )
        _insert_session(
            conn, _new_session_id(), "run", "interrupted",
            ended_at="2026-08-01T00:00:02.000Z",
            outcome_status="interrupted", outcome_reason="process_interrupted",
        )
        _insert_session(
            conn, _new_session_id(), "run", "paused",
            ended_at="2026-08-01T00:00:03.000Z",
            outcome_status="paused", outcome_reason="controlled_checkpoint_stop",
        )
        assert conn.execute(
            "SELECT status FROM crawl_sessions WHERE run_id=? ORDER BY started_at", ("run",)
        ).fetchall() == [("completed",), ("interrupted",), ("paused",)]


def test_crawl_sessions_reject_unknown_run_without_partial_row(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, _new_session_id(), "missing", "active")
        assert conn.execute("SELECT count(*) FROM crawl_sessions").fetchone() == (0,)


def test_crawl_sessions_reject_null_session_id_without_partial_row(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        _insert_run(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, None, "run", "active")
        assert conn.execute("SELECT count(*) FROM crawl_sessions").fetchone() == (0,)


def test_crawl_sessions_allow_only_one_active_session_per_run(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        _insert_run(conn)
        _insert_session(conn, _new_session_id(), "run", "active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, _new_session_id(), "run", "active")
        conn.commit()
        assert conn.execute(
            "SELECT count(*) FROM crawl_sessions WHERE run_id=? AND status='active'", ("run",)
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    ("status", "started_at", "ended_at", "outcome_status", "outcome_reason"),
    [
        ("unknown", "2026-08-01T00:00:00.000Z", None, None, None),
        ("active", None, None, None, None),
        ("active", "2026-08-01T00:00:00.00Z", None, None, None),
        ("active", "2026-08-01T00:00:00.000", None, None, None),
        ("active", "2026-13-01T00:00:00.000Z", None, None, None),
        ("completed", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000+00:00", "completed", "completed"),
        ("completed", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000", "completed", "completed"),
        ("active", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000Z", None, None),
        ("active", "2026-08-01T00:00:00.000Z", None, "completed", None),
        ("completed", "2026-08-01T00:00:00.000Z", None, "completed", "completed"),
        ("completed", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000Z", None, None),
        ("completed", "2026-08-01T00:00:00.000Z", "2026-13-01T00:00:01.000Z", "completed", "completed"),
        ("completed", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000Z", "interrupted", "process_interrupted"),
        ("paused", "2026-08-01T00:00:00.000Z", "2026-08-01T00:00:01.000Z", "arbitrary", "runtime data"),
    ],
)
def test_crawl_sessions_reject_invalid_lifecycle_rows(
    tmp_path, status, started_at, ended_at, outcome_status, outcome_reason
) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        _insert_run(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(
                conn, _new_session_id(), "run", status, started_at, ended_at,
                outcome_status, outcome_reason,
            )
        assert conn.execute("SELECT count(*) FROM crawl_sessions").fetchone() == (0,)


@pytest.mark.parametrize(
    "kind",
    ["missing_table", "missing_run_started_index", "missing_active_index", "foreign_key", "ddl", "predicate", "extra_object"],
)
def test_preflight_rejects_tampered_session_catalog_without_write(tmp_path, kind: str) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        if kind == "missing_table":
            conn.execute("DROP TABLE crawl_sessions")
        elif kind == "missing_run_started_index":
            conn.execute("DROP INDEX idx_crawl_sessions_run_started")
        elif kind == "missing_active_index":
            conn.execute("DROP INDEX idx_crawl_sessions_one_active")
        elif kind == "extra_object":
            conn.execute("CREATE INDEX idx_crawl_sessions_unexpected ON crawl_sessions(status)")
        else:
            name = "crawl_sessions" if kind in {"foreign_key", "ddl"} else "idx_crawl_sessions_one_active"
            original = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()[0]
            if kind == "foreign_key":
                tampered = original.replace("REFERENCES crawl_runs(run_id)", "REFERENCES crawl_runs(generation_id)")
            elif kind == "ddl":
                tampered = original.replace("'paused'", "'stopped'", 1)
            else:
                tampered = original.replace("WHERE status = 'active'", "WHERE status = 'completed'")
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute("UPDATE sqlite_master SET sql=? WHERE name=?", (tampered, name))
            conn.execute("PRAGMA writable_schema=OFF")
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_preflight_rejects_pre_correction_v1_catalog_without_migration(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    with sqlite3.connect(db) as conn:
        conn.execute(f"PRAGMA application_id={module.APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version={module.SCHEMA_VERSION}")
        for ddl in _PRE_CORRECTION_V1_DDL:
            conn.execute(ddl)
        conn.execute("INSERT INTO checkpoint_metadata VALUES (1, ?, 1)", (module.SCHEMA_IDENTITY,))
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


@pytest.mark.parametrize(
    "kind",
    [
        "malformed",
        "empty",
        "foreign",
        "missing_application_id",
        "old_version",
        "new_version",
        "wrong_version",
        "partial",
        "extra_table",
        "extra_index",
        "trigger",
        "view",
        "metadata",
        "duplicate_metadata",
    ],
)
def test_unknown_state_is_fail_closed_and_byte_stable(tmp_path, kind: str) -> None:
    db = tmp_path / module.DB_NAME
    if kind == "malformed":
        db.write_bytes(b"not sqlite")
    elif kind == "empty":
        db.touch()
    elif kind == "foreign":
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA application_id=77")
    elif kind == "missing_application_id":
        _valid_database(db)
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA application_id=0")
    elif kind in {"old_version", "new_version"}:
        _valid_database(db)
        version = 0 if kind == "old_version" else 2
        with sqlite3.connect(db) as conn:
            conn.execute(f"PRAGMA user_version={version}")
    elif kind == "wrong_version":
        _valid_database(db)
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA user_version=9")
    elif kind == "partial":
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE partial(x INTEGER)")
    else:
        _valid_database(db)
        with sqlite3.connect(db) as conn:
            if kind == "extra_table": conn.execute("CREATE TABLE unexpected(x INTEGER)")
            elif kind == "extra_index": conn.execute("CREATE INDEX unexpected_idx ON crawl_runs(run_id)")
            elif kind == "trigger": conn.execute("CREATE TRIGGER unexpected AFTER INSERT ON crawl_runs BEGIN SELECT 1; END")
            elif kind == "view": conn.execute("CREATE VIEW unexpected_view AS SELECT 1")
            elif kind == "metadata": conn.execute("DELETE FROM checkpoint_metadata")
            elif kind == "duplicate_metadata":
                # Build a structurally altered fixture that permits duplicate
                # singleton rows; preflight must reject it before any write.
                conn.execute("DROP TABLE checkpoint_metadata")
                conn.execute(
                    "CREATE TABLE checkpoint_metadata (singleton INTEGER CHECK (singleton = 1), "
                    "schema_identity TEXT NOT NULL, schema_version INTEGER NOT NULL)"
                )
                conn.executemany(
                    "INSERT INTO checkpoint_metadata VALUES (1, ?, 1)",
                    [(module.SCHEMA_IDENTITY,), (module.SCHEMA_IDENTITY,)],
                )
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_fk_failure_is_unknown_and_byte_stable(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("INSERT INTO include_roots VALUES ('missing', 0, 'root')")
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_preflight_observation_detects_database_replacement(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    observation = module._preflight(db)
    db.write_bytes(db.read_bytes() + b"foreign-replacement")
    assert module._observe_database(db) != observation


def test_preflight_rejects_descending_index(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP INDEX idx_inventory_occurrences_run_page")
        conn.execute(
            "CREATE INDEX idx_inventory_occurrences_run_page ON inventory_occurrences(run_id DESC, page_id)"
        )
    with pytest.raises(CheckpointStateError):
        module._preflight(db)


def test_preflight_requires_autoindex_layouts(monkeypatch, tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    layouts = dict(module._INDEX_LAYOUTS)
    layouts["crawl_runs"] = layouts["crawl_runs"][:-1]
    monkeypatch.setattr(module, "_INDEX_LAYOUTS", layouts)
    with pytest.raises(CheckpointStateError):
        module._preflight(db)


def test_preflight_rejects_case_altered_check_literal(tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)
    with sqlite3.connect(db) as conn:
        original = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='checkpoint_metadata'"
        ).fetchone()[0]
        tampered = original.replace(
            "knowledgenexus.m7.checkpoint.v1",
            "KnowledgeNexus.m7.checkpoint.v1",
        )
        assert tampered != original
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE name='checkpoint_metadata'",
            (tampered,),
        )
        conn.execute("PRAGMA writable_schema=OFF")
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_preflight_rejects_integrity_failure_without_write(tmp_path, monkeypatch) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)

    class _CursorOverride:
        def fetchone(self):
            return ("not ok",)

    class _IntegrityFailureConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        def execute(self, sql, *parameters):
            if sql.strip().lower() == "pragma integrity_check":
                return _CursorOverride()
            return self._connection.execute(sql, *parameters)

        def close(self) -> None:
            self._connection.close()

    real_connect = module.sqlite3.connect
    monkeypatch.setattr(
        module.sqlite3,
        "connect",
        lambda *args, **kwargs: _IntegrityFailureConnection(real_connect(*args, **kwargs)),
    )
    before = db.read_bytes()
    with pytest.raises(CheckpointStateError):
        module._preflight(db)
    assert db.read_bytes() == before


def test_preflight_close_failure_is_sanitized(monkeypatch, tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    _valid_database(db)

    class BrokenClose:
        def __init__(self, connection) -> None:
            self._connection = connection

        def execute(self, *args, **kwargs):
            return self._connection.execute(*args, **kwargs)

        def close(self) -> None:
            self._connection.close()
            raise RuntimeError("secret close failure")

    real_connect = module.sqlite3.connect
    monkeypatch.setattr(
        module.sqlite3,
        "connect",
        lambda *args, **kwargs: BrokenClose(real_connect(*args, **kwargs)),
    )
    with pytest.raises(CheckpointStateError) as caught:
        module._preflight(db)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_pragma_failure_is_sanitized_and_connection_rollback(monkeypatch, tmp_path) -> None:
    class Broken:
        def execute(self, sql):
            if "foreign_keys" in sql:
                raise sqlite3.OperationalError("secret pragma")
            return self
        def fetchone(self): return (0,)
        isolation_level = None
        def rollback(self): pass
    with pytest.raises(CheckpointStateError) as caught:
        module._configure_connection(Broken())
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_require_initialized_rejects_absent_database_without_schema(tmp_path) -> None:
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(
            tmp_path, require_initialized=True
        ):
            raise AssertionError("missing database must not yield a capability")
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not (tmp_path / module.DB_NAME).exists()
    assert (tmp_path / module.LOCK_NAME).exists()


def test_require_initialized_cleanup_failure_precedes_missing_database_marker(
    tmp_path, monkeypatch
) -> None:
    def fail_unlock(_lock_handle):
        raise RuntimeError("secret unlock failure")

    monkeypatch.setattr(module.portalocker, "unlock", fail_unlock)
    with pytest.raises(CheckpointStateError) as caught:
        with module._open_locked_checkpoint_workspace(
            tmp_path, require_initialized=True
        ):
            raise AssertionError("missing database must not yield a capability")
    _assert_sanitized(caught.value)
    assert not getattr(caught.value, "_missing_initial_database", False)


def test_require_initialized_opens_existing_catalog(tmp_path) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass
    with module._open_locked_checkpoint_workspace(
        tmp_path, require_initialized=True
    ) as workspace:
        assert workspace._mutate(lambda transaction: transaction._fetchone("SELECT 1")) == (1,)


def test_require_initialized_acquires_writer_lock_before_preflight_open(
    tmp_path, monkeypatch
) -> None:
    with module._open_locked_checkpoint_workspace(tmp_path):
        pass

    events = []
    real_lock = module.portalocker.lock
    real_connect = module.sqlite3.connect

    def track_lock(handle, flags, *args, **kwargs):
        events.append("lock")
        return real_lock(handle, flags, *args, **kwargs)

    def track_connect(database, *args, **kwargs):
        events.append(("connect", database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(module.portalocker, "lock", track_lock)
    monkeypatch.setattr(module.sqlite3, "connect", track_connect)

    with module._open_locked_checkpoint_workspace(
        tmp_path, require_initialized=True
    ):
        pass

    assert events.index("lock") < next(
        index for index, event in enumerate(events) if event[0] == "connect"
    )


def test_initializer_fails_closed_when_pragma_readback_is_denied(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / module.DB_NAME)

    def deny_foreign_key_readback(action, name, value, _database, _source) -> int:
        if action == sqlite3.SQLITE_PRAGMA and name == "foreign_keys" and value is None:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_foreign_key_readback)
    with pytest.raises(CheckpointStateError) as caught:
        module._initialize_or_validate_connection(conn, initialize=True)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_initialization_failure_rolls_back(monkeypatch, tmp_path) -> None:
    db = tmp_path / module.DB_NAME
    original = module._DDL[3:]
    monkeypatch.setattr(module, "_DDL", module._DDL[:2] + ("CREATE TABLE broken (",) + original)
    conn = sqlite3.connect(db)
    with pytest.raises(CheckpointStateError):
        module._initialize_or_validate_connection(conn, initialize=True)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


@pytest.mark.parametrize("fault_index", range(len(module._DDL)))
def test_each_ddl_fault_rolls_back_and_closes(monkeypatch, tmp_path, fault_index: int) -> None:
    ddl = list(module._DDL)
    ddl[fault_index] = "CREATE TABLE broken ("
    monkeypatch.setattr(module, "_DDL", tuple(ddl))
    conn = sqlite3.connect(tmp_path / f"fault-{fault_index}.sqlite3")
    with pytest.raises(CheckpointStateError):
        module._initialize_or_validate_connection(conn, initialize=True)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_metadata_insert_fault_rolls_back_and_closes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(module, "SCHEMA_IDENTITY", None)
    conn = sqlite3.connect(tmp_path / "metadata-fault.sqlite3")
    with pytest.raises(CheckpointStateError):
        module._initialize_or_validate_connection(conn, initialize=True)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
