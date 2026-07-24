from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, Iterator

RESTRICTION_SIDECAR_FORMAT_VERSION: Final = "1.0"
CAPTURED_M6B_EVIDENCE_KIND: Final = "captured_m6b_result"
SYNTHETIC_FIXTURE_EVIDENCE_KIND: Final = "synthetic_fixture"
MAX_RESTRICTION_SIDECAR_BYTES: Final = 16 * 1024 * 1024

_LOADED_EVIDENCE_KINDS = frozenset(
    {CAPTURED_M6B_EVIDENCE_KIND, SYNTHETIC_FIXTURE_EVIDENCE_KIND}
)
_SIDECAR_FIELDS = frozenset(
    {"format_version", "evidence_kind", "restriction_observations"}
)

_FILE_ATTRIBUTE_REPARSE_POINT = getattr(
    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
)
_PREPARED_TARGET_TOKEN = object()
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


class RestrictionSidecarTargetError(RuntimeError):
    """Sanitized failure from external sidecar target preflight."""

    def __init__(self) -> None:
        super().__init__("sidecar_target")


class RestrictionSidecarSerializationError(RuntimeError):
    """Sanitized failure while rendering the bounded sidecar payload."""

    def __init__(self) -> None:
        super().__init__("sidecar_serialization")


class RestrictionSidecarPublicationError(RuntimeError):
    """Sanitized failure while publishing an already-rendered sidecar."""

    def __init__(self) -> None:
        super().__init__("sidecar_publication")


class RestrictionSidecarLoadError(RuntimeError):
    """Sanitized strict-loader failure safe for operator output."""

    def __init__(self) -> None:
        super().__init__("restriction_sidecar")


@dataclass(frozen=True, repr=False)
class LoadedRestrictionSidecar:
    """Ownership-isolated parsed sidecar values without source-path identity."""

    evidence_kind: str
    restriction_observations: tuple[object, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.evidence_kind, str)
            or self.evidence_kind not in _LOADED_EVIDENCE_KINDS
        ):
            raise ValueError("evidence_kind is invalid")
        if not isinstance(self.restriction_observations, (list, tuple)):
            raise TypeError("restriction_observations expects a collection")
        object.__setattr__(
            self,
            "restriction_observations",
            tuple(deepcopy(tuple(self.restriction_observations))),
        )


@dataclass(frozen=True, repr=False)
class PreparedRestrictionSidecarTarget:
    """Preflighted external target revalidated by the publisher."""

    target_path: Path
    repository_root: Path
    _factory_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _PREPARED_TARGET_TOKEN:
            raise ValueError(
                "prepared target must come from target preflight"
            )
        if not isinstance(self.target_path, Path):
            raise TypeError("target_path expects Path")
        if not isinstance(self.repository_root, Path):
            raise TypeError("repository_root expects Path")
        if not self.target_path.is_absolute():
            raise ValueError("target_path must be absolute")
        if not self.repository_root.is_absolute():
            raise ValueError("repository_root must be absolute")


def prepare_restriction_sidecar_target(
    *,
    target_path: Path,
    repository_root: Path,
) -> PreparedRestrictionSidecarTarget:
    """Validate an absent external file target without creating anything."""

    try:
        validated_target, validated_root = _validate_target(
            target_path=target_path,
            repository_root=repository_root,
        )
    except RestrictionSidecarTargetError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RestrictionSidecarTargetError() from None
    return PreparedRestrictionSidecarTarget(
        target_path=validated_target,
        repository_root=validated_root,
        _factory_token=_PREPARED_TARGET_TOKEN,
    )


def serialize_restriction_observations(
    observations: Sequence[Mapping[str, object]],
) -> bytes:
    """Render the exact ordered M6B observations into deterministic JSON."""

    if isinstance(observations, (str, bytes)) or not isinstance(
        observations, Sequence
    ):
        raise RestrictionSidecarSerializationError()
    if not all(isinstance(observation, Mapping) for observation in observations):
        raise RestrictionSidecarSerializationError()

    payload = {
        "format_version": RESTRICTION_SIDECAR_FORMAT_VERSION,
        "evidence_kind": CAPTURED_M6B_EVIDENCE_KIND,
        "restriction_observations": observations,
    }
    try:
        rendered = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        raise RestrictionSidecarSerializationError() from None
    if len(rendered) > MAX_RESTRICTION_SIDECAR_BYTES:
        raise RestrictionSidecarSerializationError()
    return rendered


def load_restriction_sidecar(
    path: Path,
) -> tuple[LoadedRestrictionSidecar, bytes]:
    """Strict-load one stable regular sidecar and retain its exact bytes."""

    try:
        exact_bytes = _read_stable_regular_file(path)
        payload = _decode_strict_sidecar(exact_bytes)
        evidence_kind = payload["evidence_kind"]
        observations = payload["restriction_observations"]
        if not isinstance(evidence_kind, str):
            raise ValueError("evidence_kind is invalid")
        if not isinstance(observations, list):
            raise ValueError("restriction_observations is invalid")
        loaded = LoadedRestrictionSidecar(
            evidence_kind=evidence_kind,
            restriction_observations=tuple(observations),
        )
    except RestrictionSidecarLoadError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        raise RestrictionSidecarLoadError() from None
    return loaded, exact_bytes


def publish_restriction_sidecar(
    *,
    prepared_target: PreparedRestrictionSidecarTarget,
    content: bytes,
) -> None:
    """Publish exact bytes through an exclusive same-parent hard link."""

    if not isinstance(prepared_target, PreparedRestrictionSidecarTarget):
        raise TypeError(
            "prepared_target expects PreparedRestrictionSidecarTarget"
        )
    if not isinstance(content, bytes):
        raise RestrictionSidecarSerializationError()
    if len(content) > MAX_RESTRICTION_SIDECAR_BYTES:
        raise RestrictionSidecarSerializationError()

    try:
        target_path, _repository_root = _validate_target(
            target_path=prepared_target.target_path,
            repository_root=prepared_target.repository_root,
        )
    except (RestrictionSidecarTargetError, OSError, RuntimeError, ValueError):
        raise RestrictionSidecarPublicationError() from None

    file_descriptor: int | None = None
    temp_path: Path | None = None
    published = False
    try:
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        with os.fdopen(file_descriptor, "wb") as temp_file:
            file_descriptor = None
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.link(temp_path, target_path)
        published = True
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RestrictionSidecarPublicationError() from None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temp_path is not None:
            _remove_temp_best_effort(temp_path)

    if published:
        _fsync_directory_best_effort(target_path.parent)


def _read_stable_regular_file(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RestrictionSidecarLoadError()
    try:
        with _open_bound_regular_file(path) as (
            descriptor,
            before,
            stat_bound_entry,
        ):
            opened = os.fstat(descriptor)
            _require_regular_stat(opened)
            if _entry_identity(before) != _entry_identity(opened):
                raise RestrictionSidecarLoadError()
            if _stable_metadata(before) != _stable_metadata(opened):
                raise RestrictionSidecarLoadError()

            remaining = MAX_RESTRICTION_SIDECAR_BYTES + 1
            chunks: list[bytes] = []
            while remaining > 0:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)

            after_descriptor = os.fstat(descriptor)
            after_path = stat_bound_entry()
            expected_metadata = _stable_metadata(before)
            if (
                _entry_identity(after_descriptor) != _entry_identity(before)
                or _entry_identity(after_path) != _entry_identity(before)
                or _stable_metadata(after_descriptor) != expected_metadata
                or _stable_metadata(after_path) != expected_metadata
            ):
                raise RestrictionSidecarLoadError()
    except RestrictionSidecarLoadError:
        raise
    except (OSError, TypeError, ValueError):
        raise RestrictionSidecarLoadError() from None

    if not content or len(content) > MAX_RESTRICTION_SIDECAR_BYTES:
        raise RestrictionSidecarLoadError()
    return content


@contextmanager
def _open_bound_regular_file(
    path: Path,
) -> Iterator[tuple[int, os.stat_result, Callable[[], os.stat_result]]]:
    """Open a file through a verified parent chain held for the whole read."""

    if os.name == "nt":
        descriptor, before, stat_bound_entry, guards = (
            _open_windows_bound_regular_file(path)
        )
    else:
        descriptor, before, stat_bound_entry, guards = (
            _open_posix_bound_regular_file(path)
        )
    try:
        yield descriptor, before, stat_bound_entry
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        for guard in reversed(guards):
            try:
                _close_directory_guard(guard)
            except OSError:
                pass


def _open_posix_bound_regular_file(
    path: Path,
) -> tuple[
    int,
    os.stat_result,
    Callable[[], os.stat_result],
    tuple[int, ...],
]:
    _require_plain_relative_components(path.parts[1:])
    if (
        not getattr(os, "O_NOFOLLOW", 0)
        or not getattr(os, "O_DIRECTORY", 0)
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise RestrictionSidecarLoadError()
    parent_descriptor = _open_posix_plain_directory(path.anchor)
    try:
        relative_parent_parts = path.parent.parts[1:]
        for component in relative_parent_parts:
            next_descriptor = _open_posix_plain_directory(
                component,
                parent_descriptor=parent_descriptor,
            )
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor

        before = _stat_posix_bound_entry(
            parent_descriptor=parent_descriptor,
            name=path.name,
        )
        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            path.name,
            flags,
            dir_fd=parent_descriptor,
        )
    except Exception:
        try:
            os.close(parent_descriptor)
        except OSError:
            pass
        raise

    def stat_bound_entry() -> os.stat_result:
        return _stat_posix_bound_entry(
            parent_descriptor=parent_descriptor,
            name=path.name,
        )

    return descriptor, before, stat_bound_entry, (parent_descriptor,)


def _open_posix_plain_directory(
    path_or_name: str,
    *,
    parent_descriptor: int | None = None,
) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if parent_descriptor is None:
        descriptor = os.open(path_or_name, flags)
    else:
        descriptor = os.open(
            path_or_name,
            flags,
            dir_fd=parent_descriptor,
        )
    try:
        details = os.fstat(descriptor)
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise RestrictionSidecarLoadError()
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _stat_posix_bound_entry(
    *,
    parent_descriptor: int,
    name: str,
) -> os.stat_result:
    details = os.stat(
        name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    _require_regular_stat(details)
    return details


def _open_windows_bound_regular_file(
    path: Path,
) -> tuple[
    int,
    os.stat_result,
    Callable[[], os.stat_result],
    tuple[int, ...],
]:
    guards = _open_windows_plain_directory_chain(path.parent)
    descriptor: int | None = None
    try:
        parent_handle = guards[0]
        before = _stat_windows_bound_entry(
            parent_handle=parent_handle,
            name=path.name,
        )
        descriptor = _open_windows_regular_file_descriptor(
            parent_handle=parent_handle,
            name=path.name,
        )
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        for guard in reversed(guards):
            _close_windows_handle_best_effort(guard)
        raise

    def stat_bound_entry() -> os.stat_result:
        return _stat_windows_bound_entry(
            parent_handle=parent_handle,
            name=path.name,
        )

    return descriptor, before, stat_bound_entry, guards


def _open_windows_plain_directory_chain(path: Path) -> tuple[int, ...]:
    parts = path.parts
    if not parts:
        raise RestrictionSidecarLoadError()
    current_handle: int | None = None
    try:
        current_handle = _create_windows_handle(
            Path(parts[0]),
            desired_access=0x0080,  # FILE_READ_ATTRIBUTES
            flags_and_attributes=(
                0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
                | 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
            ),
        )
        _require_windows_plain_directory_handle(current_handle)
        for component in parts[1:]:
            next_handle = _open_windows_relative_handle(
                parent_handle=current_handle,
                name=component,
                directory=True,
            )
            try:
                _require_windows_plain_directory_handle(next_handle)
            except Exception:
                _close_windows_handle_best_effort(next_handle)
                raise
            _close_windows_handle(current_handle)
            current_handle = next_handle
    except Exception:
        if current_handle is not None:
            _close_windows_handle_best_effort(current_handle)
        raise
    return (current_handle,)


def _require_windows_plain_directory_handle(handle: int) -> None:
    attributes = _windows_file_attributes(handle)
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT or not (
        attributes & 0x10  # FILE_ATTRIBUTE_DIRECTORY
    ):
        raise RestrictionSidecarLoadError()


def _open_windows_regular_file_descriptor(
    *,
    parent_handle: int,
    name: str,
) -> int:
    import msvcrt

    handle = _open_windows_relative_handle(
        parent_handle=parent_handle,
        name=name,
        directory=False,
    )
    try:
        attributes = _windows_file_attributes(handle)
        if attributes & (
            _FILE_ATTRIBUTE_REPARSE_POINT
            | 0x10  # FILE_ATTRIBUTE_DIRECTORY
        ):
            raise RestrictionSidecarLoadError()
        return msvcrt.open_osfhandle(
            handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        _close_windows_handle_best_effort(handle)
        raise


def _stat_windows_bound_entry(
    *,
    parent_handle: int,
    name: str,
) -> os.stat_result:
    import msvcrt

    handle = _open_windows_relative_handle(
        parent_handle=parent_handle,
        name=name,
        directory=False,
    )
    descriptor: int | None = None
    try:
        attributes = _windows_file_attributes(handle)
        if attributes & (
            _FILE_ATTRIBUTE_REPARSE_POINT
            | 0x10  # FILE_ATTRIBUTE_DIRECTORY
        ):
            raise RestrictionSidecarLoadError()
        descriptor = msvcrt.open_osfhandle(
            handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        handle = -1
        details = os.fstat(descriptor)
        _require_regular_stat(details)
        return details
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        elif handle != -1:
            _close_windows_handle_best_effort(handle)


def _open_windows_relative_handle(
    *,
    parent_handle: int,
    name: str,
    directory: bool,
) -> int:
    import ctypes
    from ctypes import wintypes

    _require_plain_relative_components((name,))
    if "\\" in name or "/" in name:
        raise RestrictionSidecarLoadError()

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
        _fields_ = (
            ("StatusOrPointer", wintypes.LPVOID),
            ("Information", ctypes.c_size_t),
        )

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
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
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
    nt_create_file.restype = wintypes.LONG
    create_options = (
        0x00000020  # FILE_SYNCHRONOUS_IO_NONALERT
        | 0x00200000  # FILE_OPEN_REPARSE_POINT
        | (0x00000001 if directory else 0x00000040)
        # FILE_DIRECTORY_FILE / FILE_NON_DIRECTORY_FILE
    )
    status = nt_create_file(
        ctypes.byref(opened_handle),
        0x00000001  # FILE_LIST_DIRECTORY / FILE_READ_DATA
        | 0x00000080  # FILE_READ_ATTRIBUTES
        | 0x00100000,  # SYNCHRONIZE
        ctypes.byref(object_attributes),
        ctypes.byref(io_status),
        None,
        0,
        0x00000001 | 0x00000002 | 0x00000004,
        # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        1,  # FILE_OPEN
        create_options,
        None,
        0,
    )
    if status < 0 or not opened_handle.value:
        raise OSError("unable to open bound file-system handle")
    return int(opened_handle.value)


def _require_plain_relative_components(components: Sequence[str]) -> None:
    if any(
        not isinstance(component, str)
        or not component
        or component in {".", ".."}
        for component in components
    ):
        raise RestrictionSidecarLoadError()


def _create_windows_handle(
    path: Path,
    *,
    desired_access: int,
    flags_and_attributes: int,
) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        desired_access,
        0x00000001 | 0x00000002 | 0x00000004,
        # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        None,
        3,  # OPEN_EXISTING
        flags_and_attributes,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError("unable to open stable file-system handle")
    return int(handle)


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
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise OSError("unable to inspect stable file-system handle")
    return int(information.dwFileAttributes)


def _close_directory_guard(guard: int) -> None:
    if os.name == "nt":
        _close_windows_handle(guard)
    else:
        os.close(guard)


def _close_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise OSError("unable to close stable file-system handle")


def _close_windows_handle_best_effort(handle: int) -> None:
    try:
        _close_windows_handle(handle)
    except OSError:
        pass


def _require_regular_stat(details: os.stat_result) -> None:
    if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
        raise RestrictionSidecarLoadError()


def _entry_identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _stable_metadata(details: os.stat_result) -> tuple[int, int, int, int]:
    return (
        details.st_size,
        details.st_mtime_ns,
        details.st_mode,
        getattr(details, "st_file_attributes", 0),
    )


def _decode_strict_sidecar(content: bytes) -> dict[str, object]:
    if content.startswith(b"\xef\xbb\xbf"):
        raise RestrictionSidecarLoadError()
    try:
        text = content.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_non_finite_constant,
            parse_float=_parse_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise RestrictionSidecarLoadError() from None
    if not isinstance(payload, dict) or set(payload) != _SIDECAR_FIELDS:
        raise RestrictionSidecarLoadError()
    if payload.get("format_version") != RESTRICTION_SIDECAR_FORMAT_VERSION:
        raise RestrictionSidecarLoadError()
    if payload.get("evidence_kind") not in _LOADED_EVIDENCE_KINDS:
        raise RestrictionSidecarLoadError()
    if not isinstance(payload.get("restriction_observations"), list):
        raise RestrictionSidecarLoadError()
    return payload


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> object:
    raise ValueError("non-finite JSON constant")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _validate_target(
    *,
    target_path: Path,
    repository_root: Path,
) -> tuple[Path, Path]:
    if not isinstance(target_path, Path) or not isinstance(repository_root, Path):
        raise RestrictionSidecarTargetError()
    if not target_path.is_absolute() or not repository_root.is_absolute():
        raise RestrictionSidecarTargetError()
    if not _is_supported_target_name(target_path.name):
        raise RestrictionSidecarTargetError()
    if os.name == "nt" and target_path.anchor.startswith("\\\\"):
        raise RestrictionSidecarTargetError()

    try:
        validated_root = repository_root.resolve(strict=True)
    except OSError:
        raise RestrictionSidecarTargetError() from None
    if not validated_root.is_dir():
        raise RestrictionSidecarTargetError()

    if _path_entry_exists(target_path):
        raise RestrictionSidecarTargetError()

    parent = target_path.parent
    _require_plain_directory_chain(parent)
    try:
        validated_parent = parent.resolve(strict=True)
    except OSError:
        raise RestrictionSidecarTargetError() from None
    validated_target = validated_parent / target_path.name

    if _is_within(validated_target, validated_root):
        raise RestrictionSidecarTargetError()
    return validated_target, validated_root


def _require_plain_directory_chain(path: Path) -> None:
    chain = [path, *path.parents]
    for component in reversed(chain):
        try:
            details = os.lstat(component)
        except OSError:
            raise RestrictionSidecarTargetError() from None
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise RestrictionSidecarTargetError()


def _is_link_or_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _path_entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        raise RestrictionSidecarTargetError() from None
    return True


def _is_within(path: Path, parent: Path) -> bool:
    normalized_path = os.path.normcase(str(path))
    normalized_parent = os.path.normcase(str(parent))
    try:
        return os.path.commonpath((normalized_path, normalized_parent)) == (
            normalized_parent
        )
    except ValueError:
        return False


def _is_supported_target_name(name: str) -> bool:
    if (
        name in {"", ".", ".."}
        or any(
            ord(character) <= 0x1F or ord(character) == 0x7F
            for character in name
        )
    ):
        return False
    if os.name != "nt":
        return True
    if any(character in '<>:"/\\|?*' for character in name):
        return False
    if name.endswith((" ", ".")):
        return False
    base_name = name.split(".", 1)[0].rstrip(" .").upper()
    return base_name not in _WINDOWS_RESERVED_NAMES


def _remove_temp_best_effort(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _fsync_directory_best_effort(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
