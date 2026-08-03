from __future__ import annotations

import hashlib
import os
import secrets
import stat
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_artifact import (
    ConfluenceRawRestrictionArtifact,
    ConfluenceRawRestrictionPublicationOutcome,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.confluence_raw_restriction_store_port import (
    ConfluenceRawRestrictionStoreError,
    ConfluenceRawRestrictionStoreFailureCategory as FailureCategory,
    ConfluenceRawRestrictionStorePort,
)

_MAX_STABLE_READ_BYTES = 16 * 1024 * 1024
_GENERATION_RELATIVE_DIR = ("confluence", "generations")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN = 0x00000001
_FILE_CREATE = 0x00000002
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_DELETE_ON_CLOSE = 0x00001000


def _fail(category: str) -> None:
    raise ConfluenceRawRestrictionStoreError(category) from None


def _is_link_or_reparse(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _metadata(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        getattr(details, "st_nlink", 1),
    )


def _require_plain_directory(path: Path) -> None:
    try:
        details = os.lstat(path)
    except (OSError, TypeError):
        _fail(FailureCategory.RAW_ARTIFACT_INVALID)
    if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        _fail(FailureCategory.RAW_ARTIFACT_INVALID)


def _require_plain_directory_chain(path: Path) -> None:
    try:
        chain = [*path.parents, path]
        chain.reverse()
    except (AttributeError, TypeError):
        _fail(FailureCategory.RAW_ARTIFACT_INVALID)
    for component in chain:
        _require_plain_directory(component)


def _require_regular_file(path: Path) -> os.stat_result:
    try:
        details = os.lstat(path)
    except (OSError, TypeError):
        _fail(FailureCategory.RAW_ARTIFACT_INVALID)
    if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
        _fail(FailureCategory.RAW_ARTIFACT_INVALID)
    return details


def _posix_directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not getattr(os, name, 0) for name in required):
        raise OSError("bound directory operations unavailable")
    if os.open not in getattr(os, "supports_dir_fd", ()):
        raise OSError("bound directory operations unavailable")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_posix_directory_chain(path: Path, *, create: bool) -> int:
    """Open a directory chain without resolving links, retaining the leaf fd."""

    if not path.is_absolute() or not path.anchor:
        raise OSError("bound directory operations unavailable")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts[1:]):
        raise OSError("bound directory operations unavailable")
    flags = _posix_directory_flags()
    current = os.open(path.anchor, flags)
    try:
        for component in parts[1:]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                next_descriptor = os.open(component, flags, dir_fd=current)
            try:
                details = os.fstat(next_descriptor)
                if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
                    raise OSError("non-plain directory")
            except Exception:
                os.close(next_descriptor)
                raise
            os.close(current)
            current = next_descriptor
        return current
    except Exception:
        try:
            os.close(current)
        except OSError:
            pass
        raise


@contextmanager
def _open_posix_parent(path: Path, *, create: bool) -> Iterator[int]:
    descriptor = _open_posix_directory_chain(path, create=create)
    try:
        yield descriptor
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _posix_stat_entry(parent_descriptor: int, name: str) -> os.stat_result:
    if os.stat not in getattr(os, "supports_dir_fd", ()):
        raise OSError("bound entry operations unavailable")
    return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)


def _posix_open_regular(parent_descriptor: int, name: str, *, writable: bool = False) -> int:
    flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, "O_NOFOLLOW", 0)
    # Avoid blocking on a FIFO before the descriptor can be type-checked.
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        details = os.fstat(descriptor)
        if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
            raise OSError("non-regular entry")
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _posix_remove_entry(parent_descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        pass


def _posix_fsync_directory(parent_descriptor: int) -> None:
    os.fsync(parent_descriptor)


def _posix_temp_name(target_name: str) -> str:
    return f".{target_name}.{secrets.token_hex(16)}.tmp"


@contextmanager
def _open_bound_parent(path: Path, *, create: bool) -> Iterator[int]:
    """Hold a no-follow parent directory handle for the whole operation."""

    if os.name == "nt":
        with _open_windows_parent(path, create=create) as handle:
            yield handle
    else:
        with _open_posix_parent(path, create=create) as descriptor:
            yield descriptor


def _bound_stat(parent_handle: int, name: str) -> os.stat_result:
    if os.name == "nt":
        descriptor = _windows_open_regular_fd(parent_handle, name, metadata_only=True)
        try:
            return os.fstat(descriptor)
        finally:
            os.close(descriptor)
    return _posix_stat_entry(parent_handle, name)


def _bound_read(
    parent_handle: int,
    name: str,
    *,
    expected_metadata: tuple[int, int, int, int, int, int] | None = None,
) -> bytes:
    descriptor = (
        _windows_open_regular_fd(parent_handle, name)
        if os.name == "nt"
        else _posix_open_regular(parent_handle, name)
    )
    try:
        before = os.fstat(descriptor)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise OSError("non-regular entry")
        if expected_metadata is not None and _metadata(before) != expected_metadata:
            raise OSError("entry changed before read")
        if before.st_size > _MAX_STABLE_READ_BYTES:
            raise OverflowError("stable read bound exceeded")
        chunks: list[bytes] = []
        remaining = _MAX_STABLE_READ_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after_descriptor = os.fstat(descriptor)
        after_path = _bound_stat(parent_handle, name)
        content = b"".join(chunks)
        if (
            len(content) > _MAX_STABLE_READ_BYTES
            or _metadata(after_descriptor) != _metadata(before)
            or _metadata(after_path) != _metadata(before)
        ):
            raise OSError("unstable entry")
        return content
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _publish_bound(parent_handle: int, target_name: str, content: bytes) -> bool:
    """Write and link a same-parent temporary; return False on target race."""

    if os.name == "nt":
        import msvcrt

        temporary_name = f".{target_name}.{secrets.token_hex(16)}.tmp"
        temporary_handle = _windows_nt_relative_handle(
            parent_handle,
            temporary_name,
            directory=False,
            create=True,
        )
        descriptor: int | None = None
        try:
            descriptor = msvcrt.open_osfhandle(
                temporary_handle, os.O_WRONLY | getattr(os, "O_BINARY", 0)
            )
            temporary_handle = -1
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                try:
                    _windows_link_handle(
                        msvcrt.get_osfhandle(stream.fileno()), parent_handle, target_name
                    )
                except FileExistsError:
                    _windows_mark_delete(msvcrt.get_osfhandle(stream.fileno()))
                    return False
                _windows_mark_delete(msvcrt.get_osfhandle(stream.fileno()))
            return True
        except FileExistsError:
            if temporary_handle != -1:
                try:
                    _windows_mark_delete(temporary_handle)
                except OSError:
                    pass
                try:
                    _windows_close_handle(temporary_handle)
                except OSError:
                    pass
            return False
        finally:
            if temporary_handle != -1:
                try:
                    _windows_close_handle(temporary_handle)
                except OSError:
                    pass
            try:
                _windows_remove_entry(parent_handle, temporary_name)
            except OSError:
                pass

    temporary_name = _posix_temp_name(target_name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_handle)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=parent_handle,
                dst_dir_fd=parent_handle,
                follow_symlinks=False,
            )
        except FileExistsError:
            _posix_remove_entry(parent_handle, temporary_name)
            return False
        _posix_fsync_directory(parent_handle)
        _posix_remove_entry(parent_handle, temporary_name)
        return True
    finally:
        if descriptor != -1:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _posix_remove_entry(parent_handle, temporary_name)


def _windows_file_attributes(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTimeLow", wintypes.DWORD),
            ("ftCreationTimeHigh", wintypes.DWORD),
            ("ftLastAccessTimeLow", wintypes.DWORD),
            ("ftLastAccessTimeHigh", wintypes.DWORD),
            ("ftLastWriteTimeLow", wintypes.DWORD),
            ("ftLastWriteTimeHigh", wintypes.DWORD),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    getter = kernel32.GetFileInformationByHandle
    getter.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation))
    getter.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not getter(handle, ctypes.byref(information)):
        raise OSError("unable to inspect bound file-system handle")
    return int(information.dwFileAttributes)


def _windows_close_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    if not close(handle):
        raise OSError("unable to close bound file-system handle")


def _windows_open_absolute_directory(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    handle = create(
        str(path),
        0x0080,  # FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,  # OPEN_EXISTING
        0x02000000 | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        raise OSError("unable to open bound directory")
    result = int(handle)
    try:
        attributes = _windows_file_attributes(result)
        if attributes & _REPARSE_POINT or not attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("non-plain directory")
        return result
    except Exception:
        try:
            _windows_close_handle(result)
        except OSError:
            pass
        raise


def _windows_nt_relative_handle(
    parent_handle: int,
    name: str,
    *,
    directory: bool,
    create: bool = False,
    delete: bool = False,
    read_data: bool = True,
) -> int:
    import ctypes
    from ctypes import wintypes

    if not isinstance(name, str) or not name or name in {".", ".."} or "\\" in name or "/" in name:
        raise OSError("invalid bound component")

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        )

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        )

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = (("StatusOrPointer", wintypes.LPVOID), ("Information", ctypes.c_size_t))

    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        Length=encoded_length,
        MaximumLength=encoded_length + 2,
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    object_attributes = _ObjectAttributes(
        Length=ctypes.sizeof(_ObjectAttributes),
        RootDirectory=parent_handle,
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=0x00000040,  # OBJ_CASE_INSENSITIVE
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    io_status = _IoStatusBlock()
    opened_handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    nt_create = ntdll.NtCreateFile
    nt_create.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    )
    nt_create.restype = wintypes.LONG
    access = 0x00000080 | 0x00100000  # FILE_READ_ATTRIBUTES | SYNCHRONIZE
    if not directory and (read_data or create or delete):
        access |= 0x00000001  # FILE_READ_DATA
        if create or delete:
            access |= 0x00010000  # FILE_DELETE for owned temporary cleanup
    if create:
        access |= 0x00000002  # FILE_WRITE_DATA
    options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_FLAG_OPEN_REPARSE_POINT
    options |= _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
    status = nt_create(
        ctypes.byref(opened_handle),
        access,
        ctypes.byref(object_attributes),
        ctypes.byref(io_status),
        None,
        0,
        0x00000001 | 0x00000002 | 0x00000004,
        _FILE_CREATE if create else _FILE_OPEN,
        options,
        None,
        0,
    )
    if status < 0 or not opened_handle.value:
        if status in (-1073741771, -1073741770):  # STATUS_OBJECT_NAME_COLLISION/EXISTS
            raise FileExistsError(name)
        if status in (-1073741772, -1073741766):  # STATUS_OBJECT_NAME/PATH_NOT_FOUND
            raise FileNotFoundError(name)
        raise OSError("unable to open bound relative handle")
    return int(opened_handle.value)


def _windows_open_directory_chain(path: Path, *, create: bool) -> int:
    if not path.is_absolute() or not path.parts:
        raise OSError("bound directory operations unavailable")
    current = _windows_open_absolute_directory(Path(path.parts[0]))
    try:
        for component in path.parts[1:]:
            try:
                next_handle = _windows_nt_relative_handle(
                    current, component, directory=True, create=False
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    next_handle = _windows_nt_relative_handle(
                        current, component, directory=True, create=True
                    )
                except FileExistsError:
                    next_handle = _windows_nt_relative_handle(
                        current, component, directory=True, create=False
                    )
            try:
                attributes = _windows_file_attributes(next_handle)
                if attributes & _REPARSE_POINT or not attributes & _FILE_ATTRIBUTE_DIRECTORY:
                    raise OSError("non-plain directory")
            except Exception:
                try:
                    _windows_close_handle(next_handle)
                except OSError:
                    pass
                raise
            _windows_close_handle(current)
            current = next_handle
        return current
    except Exception:
        try:
            _windows_close_handle(current)
        except OSError:
            pass
        raise


@contextmanager
def _open_windows_parent(path: Path, *, create: bool) -> Iterator[int]:
    handle = _windows_open_directory_chain(path, create=create)
    try:
        yield handle
    finally:
        try:
            _windows_close_handle(handle)
        except OSError:
            pass


def _windows_open_regular_fd(
    parent_handle: int,
    name: str,
    *,
    writable: bool = False,
    metadata_only: bool = False,
) -> int:
    import msvcrt

    handle = _windows_nt_relative_handle(
        parent_handle,
        name,
        directory=False,
        read_data=not metadata_only,
    )
    try:
        attributes = _windows_file_attributes(handle)
        if attributes & _REPARSE_POINT or attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("non-regular entry")
        flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, "O_BINARY", 0)
        descriptor = msvcrt.open_osfhandle(handle, flags)
        handle = -1
        details = os.fstat(descriptor)
        if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
            os.close(descriptor)
            raise OSError("non-regular entry")
        return descriptor
    finally:
        if handle != -1:
            try:
                _windows_close_handle(handle)
            except OSError:
                pass


def _windows_mark_delete(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = (("StatusOrPointer", wintypes.LPVOID), ("Information", ctypes.c_size_t))

    class _Disposition(ctypes.Structure):
        _fields_ = (("DeleteFile", wintypes.BOOLEAN),)

    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    nt_set = ntdll.NtSetInformationFile
    nt_set.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
    )
    nt_set.restype = wintypes.LONG
    status_block = _IoStatusBlock()
    disposition = _Disposition(True)
    status = nt_set(
        handle,
        ctypes.byref(status_block),
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
        13,  # FileDispositionInformation
    )
    if status < 0:
        raise OSError("unable to remove owned temporary")


def _windows_remove_entry(parent_handle: int, name: str) -> None:
    try:
        handle = _windows_nt_relative_handle(
            parent_handle, name, directory=False, delete=True
        )
    except FileNotFoundError:
        return
    try:
        _windows_mark_delete(handle)
    finally:
        try:
            _windows_close_handle(handle)
        except OSError:
            pass


def _windows_link_handle(temp_handle: int, parent_handle: int, target_name: str) -> None:
    import ctypes
    from ctypes import wintypes

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = (("StatusOrPointer", wintypes.LPVOID), ("Information", ctypes.c_size_t))

    class _LinkInformation(ctypes.Structure):
        _fields_ = (
            ("ReplaceIfExists", wintypes.BOOLEAN),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.ULONG),
            ("FileName", wintypes.WCHAR * 1),
        )

    encoded = target_name.encode("utf-16-le")
    offset = _LinkInformation.FileName.offset
    payload = ctypes.create_string_buffer(offset + len(encoded))
    header = _LinkInformation(False, parent_handle, len(encoded), "")
    ctypes.memmove(payload, ctypes.byref(header), offset)
    ctypes.memmove(ctypes.addressof(payload) + offset, encoded, len(encoded))
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    nt_set = ntdll.NtSetInformationFile
    nt_set.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
    )
    nt_set.restype = wintypes.LONG
    status_block = _IoStatusBlock()
    status = nt_set(
        temp_handle,
        ctypes.byref(status_block),
        payload,
        len(payload),
        11,  # FileLinkInformation
    )
    if status < 0:
        if status in (-1073741771, -1073741770):
            raise FileExistsError(target_name)
        raise OSError("unable to publish bound hard link")


class ConfluenceRawRestrictionEvidenceStore(ConfluenceRawRestrictionStorePort):
    """Publishes immutable M7 restriction evidence without replacing targets."""

    def __init__(self, *, raw_root: Path) -> None:
        if not isinstance(raw_root, Path) or not raw_root.is_absolute():
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        if any(part in {".", ".."} for part in raw_root.parts):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        _require_plain_directory_chain(raw_root)
        self._raw_root = raw_root

    def resolve_restriction_path(
        self,
        *,
        run_id: CrawlRunId,
        selected_page_id: str,
        target_page_id: str,
    ) -> Path:
        _require_run_id(run_id)
        selected = _require_page_id(selected_page_id)
        target = _require_page_id(target_page_id)
        path = self._raw_root.joinpath(
            *_GENERATION_RELATIVE_DIR,
            str(run_id),
            "restrictions",
            selected,
            f"{target}.json",
        )
        try:
            path.relative_to(self._raw_root)
        except ValueError:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        return path

    def publish_restriction(
        self,
        *,
        run_id: CrawlRunId,
        envelope: ConfluenceRestrictionEvidenceEnvelope,
    ) -> ConfluenceRawRestrictionArtifact:
        _require_run_id(run_id)
        if type(envelope) is not ConfluenceRestrictionEvidenceEnvelope:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        target = self.resolve_restriction_path(
            run_id=run_id,
            selected_page_id=envelope.selected_page_id,
            target_page_id=envelope.target_page_id,
        )
        content = envelope.to_bytes()
        if len(content) > _MAX_STABLE_READ_BYTES:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        self._ensure_target_parent(target.parent)
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                try:
                    existing = _bound_stat(parent_handle, target.name)
                except FileNotFoundError:
                    existing = None
                except OSError:
                    # Classify an existing non-regular target without opening it
                    # through a potentially redirected path.
                    try:
                        observed = os.lstat(target)
                    except FileNotFoundError:
                        existing = None
                    except OSError:
                        raise
                    if _is_link_or_reparse(observed) or not stat.S_ISREG(observed.st_mode):
                        _fail(FailureCategory.RAW_ARTIFACT_INVALID)
                    raise
                if existing is not None and (
                    _is_link_or_reparse(existing) or not stat.S_ISREG(existing.st_mode)
                ):
                    _fail(FailureCategory.RAW_ARTIFACT_INVALID)
                published = _publish_bound(parent_handle, target.name, content)
            if not published:
                return self._replay_result(
                    run_id=run_id,
                    target=target,
                    expected=content,
                )
            return self._artifact(
                path=target,
                run_id=run_id,
                content=content,
                outcome=ConfluenceRawRestrictionPublicationOutcome.PUBLISHED,
            )
        except ConfluenceRawRestrictionStoreError:
            raise
        except (OSError, TypeError, ValueError):
            _fail(FailureCategory.RAW_PUBLICATION_FAILURE)

    def read_restriction(
        self,
        *,
        run_id: CrawlRunId,
        selected_page_id: str,
        target_page_id: str,
    ) -> ConfluenceRestrictionEvidenceEnvelope:
        _require_run_id(run_id)
        selected = _require_page_id(selected_page_id)
        target_page_id = _require_page_id(target_page_id)
        target = self.resolve_restriction_path(
            run_id=run_id,
            selected_page_id=selected,
            target_page_id=target_page_id,
        )
        content = self._read_stable(target)
        return self._parse_bound(
            content=content,
            selected_page_id=selected,
            target_page_id=target_page_id,
        )

    def _ensure_target_parent(self, parent: Path) -> None:
        try:
            parent.relative_to(self._raw_root)
        except ValueError:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        try:
            with _open_bound_parent(parent, create=True):
                pass
        except (FileNotFoundError, OSError, TypeError, ValueError):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)

    def _read_stable(self, target: Path) -> bytes:
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                content = _bound_read(parent_handle, target.name)
        except OverflowError:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        except ConfluenceRawRestrictionStoreError:
            raise
        except (FileNotFoundError, OSError, ValueError, TypeError):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        return content

    def _replay_result(
        self,
        *,
        run_id: CrawlRunId,
        target: Path,
        expected: bytes,
    ) -> ConfluenceRawRestrictionArtifact:
        existing = self._read_stable(target)
        envelope = self._parse_bound(
            content=existing,
            selected_page_id=target.parent.name,
            target_page_id=target.stem,
        )
        del envelope
        if existing != expected:
            _fail(FailureCategory.RAW_REPLAY_CONFLICT)
        return self._artifact(
            path=target,
            run_id=run_id,
            content=existing,
            outcome=ConfluenceRawRestrictionPublicationOutcome.REUSED,
        )

    def _parse_bound(
        self,
        *,
        content: bytes,
        selected_page_id: str,
        target_page_id: str,
    ) -> ConfluenceRestrictionEvidenceEnvelope:
        try:
            envelope = ConfluenceRestrictionEvidenceEnvelope.from_bytes(content)
        except Exception:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        if (
            envelope.selected_page_id != _require_page_id(selected_page_id)
            or envelope.target_page_id != _require_page_id(
                target_page_id.removesuffix(".json")
            )
        ):
            _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
        return envelope

    @staticmethod
    def _artifact(
        *,
        path: Path,
        run_id: CrawlRunId,
        content: bytes,
        outcome: ConfluenceRawRestrictionPublicationOutcome,
    ) -> ConfluenceRawRestrictionArtifact:
        return ConfluenceRawRestrictionArtifact(
            path=path,
            run_id=run_id,
            raw_sha256=hashlib.sha256(content).hexdigest(),
            byte_count=len(content),
            outcome=outcome,
        )


def _require_run_id(value: object) -> CrawlRunId:
    if type(value) is not CrawlRunId:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    try:
        rebuilt = CrawlRunId(value.value)
    except Exception:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    if rebuilt != value:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    return rebuilt


def _require_page_id(value: object) -> str:
    try:
        return require_confluence_page_id(value)
    except (TypeError, ValueError):
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)


__all__ = ["ConfluenceRawRestrictionEvidenceStore"]
