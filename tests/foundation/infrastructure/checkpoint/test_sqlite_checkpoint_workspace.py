from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from knowledgenexus.foundation.infrastructure.checkpoint import sqlite_checkpoint_workspace as module
from knowledgenexus.foundation.ports import CheckpointStateError


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
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 9
    assert module._preflight(tmp_path / module.DB_NAME).absent is False


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
