from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import TracebackType

import portalocker

from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)


DB_NAME = "crawl_state.sqlite3"
LOCK_NAME = "crawl_writer.lock"
SIDECARS = (DB_NAME + "-journal", DB_NAME + "-wal", DB_NAME + "-shm")
_SIDECARS = SIDECARS
DERIVED_NAMES = (DB_NAME, LOCK_NAME, *SIDECARS)


def _failure() -> CheckpointStateError:
    return CheckpointStateError()


def _raise_failure() -> None:
    try:
        raise _failure() from None
    except CheckpointStateError as error:
        error.__cause__ = None
        error.__context__ = None
        raise


def _reparse(info: os.stat_result) -> bool:
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _entry_metadata(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        getattr(info, "st_nlink", 1),
    )


def _lock_metadata_matches(
    expected: tuple[int, int, int, int, int, int, int],
    current: tuple[int, int, int, int, int, int, int],
) -> bool:
    """Compare lock identity and safety fields without timestamp churn."""
    return expected[:4] == current[:4] and expected[6] == current[6]


@dataclass(frozen=True)
class _EntryObservation:
    absent: bool
    metadata: tuple[int, int, int, int, int, int, int] | None

    @property
    def identity(self) -> tuple[int, int] | None:
        return None if self.metadata is None else self.metadata[:2]


def _observe(path: Path, *, directory: bool = False) -> _EntryObservation:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _EntryObservation(True, None)
    except Exception:
        _raise_failure()
    if stat.S_ISLNK(info.st_mode) or _reparse(info):
        _raise_failure()
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode)
    if not valid:
        _raise_failure()
    return _EntryObservation(False, _entry_metadata(info))


def _workspace_chain(workspace: Path) -> tuple[tuple[int, int, int, int, int, int, int], ...]:
    try:
        chain = list(workspace.parents)[::-1] + [workspace]
        observations = tuple(_observe(item, directory=True) for item in chain)
    except CheckpointStateError:
        raise
    except Exception:
        _raise_failure()
    if any(item.absent or item.metadata is None for item in observations):
        _raise_failure()
    return tuple(item.metadata for item in observations if item.metadata is not None)


def _validate_workspace(value: Path) -> tuple[Path, Path, tuple, dict[str, _EntryObservation]]:
    if type(value) is not type(Path()) or not value.is_absolute():
        _raise_failure()
    if any(part in (".", "..") for part in value.parts):
        _raise_failure()
    windows = PureWindowsPath(str(value))
    if str(value).startswith("\\\\") or (windows.drive and not windows.root):
        _raise_failure()
    try:
        workspace_observation = _observe(value, directory=True)
        if workspace_observation.absent:
            _raise_failure()
        chain = _workspace_chain(value)
        entries = {name: _observe(value / name) for name in DERIVED_NAMES}
    except CheckpointStateError:
        raise
    except Exception:
        _raise_failure()
    return (
        value / DB_NAME,
        value / LOCK_NAME,
        chain,
        entries,
    )


def _open_posix_workspace_fd(workspace: Path) -> int:
    """Anchor every workspace component before opening a derived entry."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        _raise_failure()
    descriptor = None
    try:
        descriptor = os.open(workspace.anchor, os.O_RDONLY | directory | nofollow)
        for component in workspace.parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | directory | nofollow,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except CheckpointStateError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass
        _raise_failure()


def _verify_windows_handle_target(descriptor: int, lock: Path) -> None:
    """Reject a handle that resolved through a swapped ancestor."""
    if os.name != "nt":
        return
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_path = kernel32.GetFinalPathNameByHandleW
        get_path.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        get_path.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_path(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            _raise_failure()
        actual = os.path.normcase(buffer.value)
        expected = os.path.normcase(os.path.abspath(os.fspath(lock)))
        if actual.startswith("\\\\?\\"):
            actual = actual[4:]
        if expected.startswith("\\\\?\\"):
            expected = expected[4:]
        if actual != expected:
            _raise_failure()
    except CheckpointStateError:
        raise
    except Exception:
        _raise_failure()


def _open_lock_descriptor(lock: Path, workspace: Path, flags: int) -> int:
    """Open the lock without following a replaced ancestor or final entry."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None and os.name != "nt":
        workspace_descriptor = _open_posix_workspace_fd(workspace)
        try:
            return os.open(
                lock.name,
                flags | nofollow,
                0o600,
                dir_fd=workspace_descriptor,
            )
        finally:
            os.close(workspace_descriptor)
    if os.name != "nt":
        _raise_failure()
    # Python's Windows os.open has no O_NOFOLLOW. CreateFileW with
    # FILE_FLAG_OPEN_REPARSE_POINT is the platform equivalent; if it cannot
    # be obtained, this seam fails closed rather than following a redirect.
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create_file.restype = ctypes.c_void_p
        handle = create_file(
            str(lock),
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE
            0x00000007,  # FILE_SHARE_READ | WRITE | DELETE
            None,
            4,  # OPEN_ALWAYS
            0x00000080 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT
            None,
        )
        raw_handle = getattr(handle, "value", handle)
        invalid = ctypes.c_void_p(-1).value
        if raw_handle in (None, invalid):
            _raise_failure()
        descriptor = None
        try:
            descriptor = msvcrt.open_osfhandle(
                raw_handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
            )
            _verify_windows_handle_target(descriptor, lock)
            return descriptor
        except Exception:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except Exception:
                    pass
            else:
                kernel32.CloseHandle(raw_handle)
            _raise_failure()
    except CheckpointStateError:
        raise
    except Exception:
        _raise_failure()


def _open_lock(workspace: Path, lock: Path, prior: _EntryObservation):
    flags = os.O_RDWR | os.O_CREAT
    descriptor = None
    handle = None
    success = False
    try:
        descriptor = _open_lock_descriptor(lock, workspace, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or _reparse(info):
            _raise_failure()
        metadata = _entry_metadata(info)
        if not prior.absent and not _lock_metadata_matches(prior.metadata, metadata):
            _raise_failure()
        handle = os.fdopen(descriptor, "r+b")
        descriptor = None
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        success = True
        return handle, metadata
    except CheckpointStateError:
        raise
    except Exception:
        _raise_failure()
    finally:
        if handle is not None and not success:
            try:
                handle.close()
            except Exception:
                pass
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass


class _WriterLockLease:
    """Private lease carrying only infrastructure state to the opener."""

    __slots__ = (
        "_workspace",
        "_lock",
        "_handle",
        "_lock_metadata",
        "_workspace_chain",
        "_entries",
        "_active",
    )

    def __init__(self, workspace: Path, lock: Path, handle, lock_metadata, chain, entries):
        self._workspace = workspace
        self._lock = lock
        self._handle = handle
        self._lock_metadata = lock_metadata
        self._workspace_chain = chain
        self._entries = entries
        self._active = True

    def __enter__(self):
        if not self._active:
            _raise_failure()
        return self

    # A lease owns one live OS handle. Copying it would create a second
    # apparent owner whose close could release the first owner's lock.
    def __copy__(self):
        _raise_failure()

    def __deepcopy__(self, memo):
        del memo
        _raise_failure()

    def __reduce__(self):
        _raise_failure()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.close()
        return None

    def _verify(self, *, allow_sidecar_lifecycle: bool = False) -> None:
        if not self._active:
            _raise_failure()
        _, lock, chain, entries = _validate_workspace(self._workspace)
        if lock != self._lock or not self._chain_matches(chain, allow_sidecar_lifecycle):
            _raise_failure()
        current_lock = entries[LOCK_NAME]
        if current_lock.absent or current_lock.metadata != self._lock_metadata:
            _raise_failure()
        for name, expected in self._entries.items():
            # Database metadata is owned by the SQLite seam. SQLite sidecars
            # are lifecycle-managed: a journal/WAL/SHM can be created, resized,
            # and removed during a valid transaction. Their paths are still
            # checked no-follow on every pass, and an existing sidecar cannot
            # silently be replaced by another inode.
            if name in (DB_NAME, LOCK_NAME):
                continue
            current = entries[name]
            if current.absent:
                if expected.absent or allow_sidecar_lifecycle:
                    continue
                _raise_failure()
            if expected.absent:
                if allow_sidecar_lifecycle:
                    continue
                _raise_failure()
            if current.metadata != expected.metadata and not allow_sidecar_lifecycle:
                _raise_failure()

    def _chain_matches(self, current, allow_lifecycle: bool) -> bool:
        if current == self._workspace_chain:
            return True
        if not allow_lifecycle or len(current) != len(self._workspace_chain):
            return False
        # SQLite sidecar creation/removal changes only the workspace directory's
        # directory metadata; ancestors must remain byte-for-byte unchanged.
        for index, (before, after) in enumerate(zip(self._workspace_chain, current)):
            if index < len(current) - 1:
                if before != after:
                    return False
                continue
            if before[:2] != after[:2] or before[2] != after[2] or before[6] != after[6]:
                return False
        return True

    def _refresh_workspace_chain(self) -> None:
        """Advance the chain after a permitted derived-entry lifecycle change."""
        _, lock, chain, entries = _validate_workspace(self._workspace)
        if lock != self._lock or not self._chain_matches(chain, True):
            _raise_failure()
        if entries[LOCK_NAME].metadata != self._lock_metadata:
            _raise_failure()
        self._workspace_chain = chain

    def _refresh_sidecars(self) -> None:
        """Record SQLite's committed sidecar lifecycle for the next unit."""
        self._refresh_workspace_chain()
        _, lock, _chain, entries = _validate_workspace(self._workspace)
        if lock != self._lock or entries[LOCK_NAME].metadata != self._lock_metadata:
            _raise_failure()
        for name in SIDECARS:
            self._entries[name] = entries[name]

    def close(self) -> None:
        if not self._active:
            return
        self._active = False
        handle = self._handle
        self._handle = None
        failure = False
        if handle is not None:
            try:
                portalocker.unlock(handle)
            except Exception:
                failure = True
            try:
                handle.close()
            except Exception:
                failure = True
        if failure:
            _raise_failure()


def _acquire_writer_lock(workspace: Path) -> _WriterLockLease:
    db, lock, chain, entries = _validate_workspace(workspace)
    del db
    prior_lock = entries[LOCK_NAME]
    handle = None
    try:
        handle, lock_metadata = _open_lock(workspace, lock, prior_lock)
        # Revalidate every derived path after locking; no SQLite operation can
        # begin until this identity snapshot is stable.
        _, checked_lock, checked_chain, checked_entries = _validate_workspace(workspace)
        # Creating a previously absent lock legitimately updates the parent
        # directory timestamps; the post-acquisition snapshot becomes the
        # lease baseline while the path identity is still checked.
        if checked_lock != lock:
            _raise_failure()
        if not _lock_metadata_matches(
            lock_metadata, checked_entries[LOCK_NAME].metadata
        ):
            _raise_failure()
        lock_metadata = checked_entries[LOCK_NAME].metadata
        return _WriterLockLease(
            workspace,
            lock,
            handle,
            lock_metadata,
            checked_chain,
            checked_entries,
        )
    except CheckpointStateError:
        if handle is not None:
            try:
                portalocker.unlock(handle)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        raise
    except Exception:
        if handle is not None:
            try:
                portalocker.unlock(handle)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        _raise_failure()


def _guard_workspace(workspace: Path) -> tuple[Path, Path]:
    """Compatibility guard used by the private SQLite adapter."""
    database, lock, _chain, _entries = _validate_workspace(workspace)
    return database, lock


__all__ = []
