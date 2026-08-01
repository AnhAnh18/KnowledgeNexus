from __future__ import annotations

import sqlite3
import stat
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)

APPLICATION_ID = 1263425591
SCHEMA_VERSION = 1
SCHEMA_IDENTITY = "knowledgenexus.m7.checkpoint.v1"
DB_NAME = "crawl_state.sqlite3"
LOCK_NAME = "crawl_writer.lock"
_SIDECARS = (DB_NAME + "-journal", DB_NAME + "-wal", DB_NAME + "-shm")

# C3-A owns the portalocker lease and workspace-opening sequence. C2-A keeps
# only these private path, read-only validation, and connection-init seams.
_DDL = (
    "CREATE TABLE checkpoint_metadata (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), schema_identity TEXT NOT NULL CHECK (schema_identity = 'knowledgenexus.m7.checkpoint.v1'), schema_version INTEGER NOT NULL CHECK (schema_version = 1))",
    "CREATE TABLE crawl_runs (run_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL UNIQUE, fingerprint_digest TEXT NOT NULL CHECK (length(fingerprint_digest) > 0), status TEXT NOT NULL CHECK (status IN ('incomplete','complete')), inventory_phase TEXT NOT NULL CHECK (inventory_phase IN ('pending','complete')), created_at TEXT NOT NULL)",
    "CREATE TABLE crawl_sessions (session_id TEXT PRIMARY KEY NOT NULL CHECK (length(session_id) > 0), run_id TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('active','completed','interrupted','paused')), started_at TEXT NOT NULL CHECK (length(started_at) = 24 AND COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ', started_at) = started_at, 0)), ended_at TEXT CHECK (ended_at IS NULL OR (length(ended_at) = 24 AND COALESCE(strftime('%Y-%m-%dT%H:%M:%fZ', ended_at) = ended_at, 0))), outcome_status TEXT, outcome_reason TEXT, CHECK (COALESCE((status = 'active' AND ended_at IS NULL AND outcome_status IS NULL AND outcome_reason IS NULL) OR (status = 'completed' AND ended_at IS NOT NULL AND outcome_status = 'completed' AND outcome_reason = 'completed') OR (status = 'interrupted' AND ended_at IS NOT NULL AND outcome_status = 'interrupted' AND outcome_reason = 'process_interrupted') OR (status = 'paused' AND ended_at IS NOT NULL AND outcome_status = 'paused' AND outcome_reason = 'controlled_checkpoint_stop'), 0)), FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id))",
    "CREATE INDEX idx_crawl_sessions_run_started ON crawl_sessions(run_id, started_at)",
    "CREATE UNIQUE INDEX idx_crawl_sessions_one_active ON crawl_sessions(run_id) WHERE status = 'active'",
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
_OBJECTS = {"checkpoint_metadata", "crawl_runs", "crawl_sessions", "include_roots", "root_occurrences", "root_progress", "inventory_windows", "inventory_occurrences", "checkpoint_transitions", "request_budget_reservations", "idx_crawl_sessions_run_started", "idx_crawl_sessions_one_active", "idx_inventory_occurrences_run_page", "idx_inventory_windows_run_root", "idx_root_progress_incomplete"}

# These PRAGMA tuples deliberately include properties that SQLite's DDL text
# alone cannot prove after a catalog-text tamper.
_TABLE_LAYOUTS = {
    "checkpoint_metadata": (("singleton", "INTEGER", 0, 1), ("schema_identity", "TEXT", 1, 0), ("schema_version", "INTEGER", 1, 0)),
    "crawl_runs": (("run_id", "TEXT", 0, 1), ("generation_id", "TEXT", 1, 0), ("fingerprint_digest", "TEXT", 1, 0), ("status", "TEXT", 1, 0), ("inventory_phase", "TEXT", 1, 0), ("created_at", "TEXT", 1, 0)),
    "crawl_sessions": (("session_id", "TEXT", 1, 1), ("run_id", "TEXT", 1, 0), ("status", "TEXT", 1, 0), ("started_at", "TEXT", 1, 0), ("ended_at", "TEXT", 0, 0), ("outcome_status", "TEXT", 0, 0), ("outcome_reason", "TEXT", 0, 0)),
    "include_roots": (("run_id", "TEXT", 1, 1), ("include_root_ordinal", "INTEGER", 1, 2), ("include_root_page_id", "TEXT", 1, 0)),
    "root_occurrences": (("run_id", "TEXT", 1, 1), ("include_root_ordinal", "INTEGER", 1, 2), ("page_id", "TEXT", 1, 0), ("title", "TEXT", 1, 0), ("space_key", "TEXT", 1, 0), ("parent_page_id", "TEXT", 0, 0), ("updated_at", "TEXT", 0, 0), ("source_version", "TEXT", 0, 0), ("ancestor_page_ids_json", "TEXT", 1, 0), ("ancestor_titles_json", "TEXT", 1, 0), ("labels_json", "TEXT", 1, 0), ("attachment_count", "INTEGER", 0, 0)),
    "root_progress": (("run_id", "TEXT", 1, 1), ("include_root_ordinal", "INTEGER", 1, 2), ("progress", "TEXT", 1, 0), ("next_start", "INTEGER", 0, 0), ("descendants_complete", "INTEGER", 1, 0)),
    "inventory_windows": (("run_id", "TEXT", 1, 1), ("include_root_ordinal", "INTEGER", 1, 2), ("requested_start", "INTEGER", 1, 3), ("observed_start", "INTEGER", 1, 0), ("response_size", "INTEGER", 1, 0), ("total_size", "INTEGER", 1, 0), ("next_start", "INTEGER", 1, 0), ("terminal", "INTEGER", 1, 0)),
    "inventory_occurrences": (("run_id", "TEXT", 1, 1), ("include_root_ordinal", "INTEGER", 1, 2), ("window_start", "INTEGER", 1, 3), ("item_ordinal", "INTEGER", 1, 4), ("page_id", "TEXT", 1, 0), ("title", "TEXT", 1, 0), ("space_key", "TEXT", 1, 0), ("parent_page_id", "TEXT", 0, 0), ("updated_at", "TEXT", 0, 0), ("source_version", "TEXT", 0, 0), ("ancestor_page_ids_json", "TEXT", 1, 0), ("ancestor_titles_json", "TEXT", 1, 0), ("labels_json", "TEXT", 1, 0), ("attachment_count", "INTEGER", 0, 0)),
    "checkpoint_transitions": (("run_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2), ("include_root_ordinal", "INTEGER", 1, 0), ("from_progress", "TEXT", 1, 0), ("to_progress", "TEXT", 1, 0)),
    "request_budget_reservations": (("run_id", "TEXT", 1, 1), ("reservation_sequence", "INTEGER", 1, 2), ("reserved_at", "TEXT", 1, 0)),
}
_FOREIGN_KEY_LAYOUTS = {
    "include_roots": ((0, 0, "crawl_runs", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"),),
    "root_occurrences": ((0, 0, "include_roots", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"), (0, 1, "include_roots", "include_root_ordinal", "include_root_ordinal", "NO ACTION", "NO ACTION", "NONE")),
    "root_progress": ((0, 0, "include_roots", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"), (0, 1, "include_roots", "include_root_ordinal", "include_root_ordinal", "NO ACTION", "NO ACTION", "NONE")),
    "inventory_windows": ((0, 0, "include_roots", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"), (0, 1, "include_roots", "include_root_ordinal", "include_root_ordinal", "NO ACTION", "NO ACTION", "NONE")),
    "inventory_occurrences": ((0, 0, "inventory_windows", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"), (0, 1, "inventory_windows", "include_root_ordinal", "include_root_ordinal", "NO ACTION", "NO ACTION", "NONE"), (0, 2, "inventory_windows", "window_start", "requested_start", "NO ACTION", "NO ACTION", "NONE")),
    "checkpoint_transitions": ((0, 0, "include_roots", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"), (0, 1, "include_roots", "include_root_ordinal", "include_root_ordinal", "NO ACTION", "NO ACTION", "NONE")),
    "request_budget_reservations": ((0, 0, "crawl_runs", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"),),
    "crawl_sessions": ((0, 0, "crawl_runs", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"),),
}
_EXPLICIT_INDEX_LAYOUTS = {
    "inventory_occurrences": ("idx_inventory_occurrences_run_page", ((0, 0, "run_id", 0, "BINARY", 1), (1, 4, "page_id", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
    "inventory_windows": ("idx_inventory_windows_run_root", ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, 2, "requested_start", 0, "BINARY", 1), (3, -1, None, 0, "BINARY", 0))),
    "root_progress": ("idx_root_progress_incomplete", ((0, 0, "run_id", 0, "BINARY", 1), (1, 4, "descendants_complete", 0, "BINARY", 1), (2, 1, "include_root_ordinal", 0, "BINARY", 1), (3, -1, None, 0, "BINARY", 0))),
}
_INDEX_LAYOUTS = {
    "checkpoint_metadata": (),
    "crawl_runs": (
        (0, "sqlite_autoindex_crawl_runs_2", 1, "u", 0, ((0, 1, "generation_id", 0, "BINARY", 1), (1, -1, None, 0, "BINARY", 0))),
        (1, "sqlite_autoindex_crawl_runs_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, -1, None, 0, "BINARY", 0))),
    ),
    "include_roots": (
        (0, "sqlite_autoindex_include_roots_2", 1, "u", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 2, "include_root_page_id", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
        (1, "sqlite_autoindex_include_roots_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
    ),
    "root_occurrences": ((0, "sqlite_autoindex_root_occurrences_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),),
    "root_progress": (
        (0, "idx_root_progress_incomplete", 0, "c", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 4, "descendants_complete", 0, "BINARY", 1), (2, 1, "include_root_ordinal", 0, "BINARY", 1), (3, -1, None, 0, "BINARY", 0))),
        (1, "sqlite_autoindex_root_progress_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
    ),
    "inventory_windows": (
        (0, "idx_inventory_windows_run_root", 0, "c", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, 2, "requested_start", 0, "BINARY", 1), (3, -1, None, 0, "BINARY", 0))),
        (1, "sqlite_autoindex_inventory_windows_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, 2, "requested_start", 0, "BINARY", 1), (3, -1, None, 0, "BINARY", 0))),
    ),
    "inventory_occurrences": (
        (0, "idx_inventory_occurrences_run_page", 0, "c", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 4, "page_id", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
        (1, "sqlite_autoindex_inventory_occurrences_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "include_root_ordinal", 0, "BINARY", 1), (2, 2, "window_start", 0, "BINARY", 1), (3, 3, "item_ordinal", 0, "BINARY", 1), (4, -1, None, 0, "BINARY", 0))),
    ),
    "checkpoint_transitions": ((0, "sqlite_autoindex_checkpoint_transitions_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "sequence", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),),
    "request_budget_reservations": ((0, "sqlite_autoindex_request_budget_reservations_1", 1, "pk", 0, ((0, 0, "run_id", 0, "BINARY", 1), (1, 1, "reservation_sequence", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),),
    "crawl_sessions": (
        (0, "idx_crawl_sessions_one_active", 1, "c", 1, ((0, 1, "run_id", 0, "BINARY", 1), (1, -1, None, 0, "BINARY", 0))),
        (1, "idx_crawl_sessions_run_started", 0, "c", 0, ((0, 1, "run_id", 0, "BINARY", 1), (1, 3, "started_at", 0, "BINARY", 1), (2, -1, None, 0, "BINARY", 0))),
        (2, "sqlite_autoindex_crawl_sessions_1", 1, "pk", 0, ((0, 0, "session_id", 0, "BINARY", 1), (1, -1, None, 0, "BINARY", 0))),
    ),
}


@dataclass(frozen=True)
class _DatabaseObservation:
    absent: bool
    identity: tuple[int, int, int, int] | None


def _fail() -> CheckpointStateError:
    return CheckpointStateError()


def _reject_reparse(path: Path) -> None:
    failed = False
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise _fail()
        attrs = getattr(info, "st_file_attributes", 0)
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise _fail()
    except CheckpointStateError:
        failed = True
    except Exception:
        failed = True
    if failed:
        raise _fail()


def _reject_directory_or_nonregular_file(path: Path) -> None:
    failed = False
    try:
        info = path.lstat()
        attrs = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise _fail()
    except CheckpointStateError:
        failed = True
    except Exception:
        failed = True
    if failed:
        raise _fail()


def _guard_workspace(value: Path) -> tuple[Path, Path]:
    if type(value) is not type(Path()) or not value.is_absolute():
        raise _fail()
    if any(part in (".", "..") for part in value.parts):
        raise _fail()
    win = PureWindowsPath(str(value))
    if win.drive and not win.root or str(value).startswith("\\\\"):
        raise _fail()
    failed = False
    result = None
    try:
        if not value.exists() or not value.is_dir():
            raise _fail()
        # Validate every existing ancestor down to the workspace.
        chain = list(value.parents)[::-1] + [value]
        for ancestor in chain:
            if ancestor.exists():
                _reject_reparse(ancestor)
        db = value / DB_NAME
        lock = value / LOCK_NAME
        for child_name in (DB_NAME, LOCK_NAME, *_SIDECARS):
            child = value / child_name
            try:
                child.lstat()
            except FileNotFoundError:
                continue
            except Exception:
                raise _fail()
            _reject_directory_or_nonregular_file(child)
        result = (db, lock)
    except CheckpointStateError:
        failed = True
    except Exception:
        failed = True
    if failed:
        raise _fail()
    assert result is not None
    return result


def _normalized_sql(sql: str | None) -> str:
    return " ".join((sql or "").replace("\n", " ").split())


def _observe_database(path: Path) -> _DatabaseObservation:
    failed = False
    try:
        if not path.exists():
            return _DatabaseObservation(True, None)
        info = path.stat()
        return _DatabaseObservation(False, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
    except Exception:
        failed = True
    if failed:
        raise _fail()


def _validate_database_catalog(conn: sqlite3.Connection) -> None:
    """Verify the complete schema without changing connection state."""
    if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise _fail()
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise _fail()
    objects = {
        row[0]: (row[1], row[2])
        for row in conn.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    if set(objects) != _OBJECTS or any(
        objects[n][0] != ("index" if n.startswith("idx_") else "table")
        for n in _OBJECTS
    ):
        raise _fail()
    for ddl in _DDL:
        tokens = ddl.split()
        name = tokens[3] if tokens[1] == "UNIQUE" else tokens[2]
        if _normalized_sql(objects[name][1]) != _normalized_sql(ddl):
            raise _fail()
    for table, layout in _TABLE_LAYOUTS.items():
        actual = tuple(
            (row[0], row[1], row[2].upper(), row[3], row[4], row[5])
            for row in conn.execute(f"PRAGMA table_info({table})")
        )
        expected = tuple(
            (cid, name, declared_type, notnull, None, pk)
            for cid, (name, declared_type, notnull, pk) in enumerate(layout)
        )
        if actual != expected:
            raise _fail()
    for table, expected in _FOREIGN_KEY_LAYOUTS.items():
        actual = tuple(
            tuple(row[:8]) for row in conn.execute(f"PRAGMA foreign_key_list({table})")
        )
        if actual != expected:
            raise _fail()
    for table, expected_indexes in _INDEX_LAYOUTS.items():
        actual_indexes = tuple(
            tuple(row[:5]) for row in conn.execute(f"PRAGMA index_list({table})")
        )
        if actual_indexes != tuple(index[:5] for index in expected_indexes):
            raise _fail()
        for expected_index in expected_indexes:
            actual_xinfo = tuple(
                tuple(row[:6])
                for row in conn.execute(f"PRAGMA index_xinfo({expected_index[1]})")
            )
            if actual_xinfo != expected_index[5]:
                raise _fail()
    if _normalized_sql(objects["idx_crawl_sessions_one_active"][1]) != (
        "CREATE UNIQUE INDEX idx_crawl_sessions_one_active ON crawl_sessions(run_id) "
        "WHERE status = 'active'"
    ):
        raise _fail()
    row = conn.execute(
        "SELECT singleton,schema_identity,schema_version FROM checkpoint_metadata"
    ).fetchall()
    if row != [(1, SCHEMA_IDENTITY, SCHEMA_VERSION)]:
        raise _fail()
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise _fail()
    if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise _fail()


def _preflight(path: Path) -> _DatabaseObservation:
    """Read-only catalog/header verification. Returns true when DB is absent."""
    observation = _observe_database(path)
    if observation.absent:
        return observation
    if observation.identity[2] == 0:
        raise _fail()
    uri = "file:" + quote(path.as_posix(), safe="/:\\") + "?mode=ro"
    conn = None
    failed = False
    result = None
    try:
        conn = sqlite3.connect(uri, uri=True)
        _validate_database_catalog(conn)
        result = observation
    except CheckpointStateError:
        failed = True
    except Exception:
        failed = True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                failed = True
    if failed:
        # This raise is deliberately outside the exception handler: callers
        # must not be able to recover a filesystem/SQLite error from context.
        raise _fail()
    assert result is not None
    return result


def _configure_connection(conn: sqlite3.Connection) -> None:
    failed = False
    try:
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1: raise _fail()
        conn.execute("PRAGMA busy_timeout=0")
        if conn.execute("PRAGMA busy_timeout").fetchone()[0] != 0: raise _fail()
        conn.execute("PRAGMA journal_mode=DELETE")
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "delete": raise _fail()
        conn.execute("PRAGMA synchronous=EXTRA")
        if conn.execute("PRAGMA synchronous").fetchone()[0] != 3: raise _fail()
    except CheckpointStateError:
        failed = True
    except Exception:
        failed = True
    if failed:
        raise _fail()


def _initialize_or_validate_connection(conn: sqlite3.Connection, *, initialize: bool | None = None) -> int:
    if type(conn) is not sqlite3.Connection:
        raise _fail()
    failed = False
    try:
        if type(initialize) is not bool:
            # The caller must derive this decision from path preflight; a
            # connection alone cannot distinguish missing from empty state.
            raise _fail()
        if not initialize:
            _validate_database_catalog(conn)
        _configure_connection(conn)
        if initialize:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            for ddl in _DDL:
                conn.execute(ddl)
            conn.execute("INSERT INTO checkpoint_metadata VALUES (1, ?, 1)", (SCHEMA_IDENTITY,))
            conn.commit()
        return SCHEMA_VERSION
    except CheckpointStateError:
        try: conn.rollback()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        failed = True
    except Exception:
        try: conn.rollback()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        failed = True
    if failed:
        raise _fail()
    return SCHEMA_VERSION


__all__ = []
