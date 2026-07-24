from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

RESTRICTION_SIDECAR_FORMAT_VERSION: Final = "1.0"
CAPTURED_M6B_EVIDENCE_KIND: Final = "captured_m6b_result"
MAX_RESTRICTION_SIDECAR_BYTES: Final = 16 * 1024 * 1024

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
