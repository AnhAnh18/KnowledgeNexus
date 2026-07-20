from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)

# Restricting the path segment to the numeric page-id shape is the strictest
# possible rule and, on its own, makes directory traversal impossible. This is
# intentionally not a loose path sanitizer.
_PAGES_SUBDIR = ("confluence", "pages")


class ConfluenceRawPageStoreError(RuntimeError):
    """A raw page could not be published to its deterministic path."""


@dataclass(frozen=True)
class RawPageArtifact:
    """Minimal metadata about a persisted raw page. No raw content."""

    path: Path
    raw_sha256: str
    byte_count: int


class ConfluenceRawPageStore:
    """Persists one raw Confluence page response at a deterministic path.

    The final path represents the current raw page and may be replaced by a
    later successful run. Publication is atomic: an exclusively created
    same-directory temporary is written, flushed, fsynced, closed, then
    `os.replace`d over the target. A failure never exposes a partial final file
    and never deletes a prior final file or any unrelated entry.
    """

    def __init__(self, *, raw_root: Path) -> None:
        if not isinstance(raw_root, Path):
            raise TypeError("raw_root expects a pathlib.Path")
        self._raw_root = raw_root

    def resolve_path(self, *, page_id: str) -> Path:
        page_id = _require_page_id(page_id)
        resolved_root = self._raw_root.resolve()
        target = resolved_root.joinpath(*_PAGES_SUBDIR, f"{page_id}.json")
        resolved_target = _resolve_without_requiring_existence(target)
        if not _is_within(resolved_target, resolved_root):
            raise ConfluenceRawPageStoreError(
                "resolved raw page path escapes the raw root"
            )
        return resolved_target

    def write(self, *, page_id: str, raw_bytes: bytes) -> RawPageArtifact:
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError("raw_bytes expects bytes")
        raw_bytes = bytes(raw_bytes)
        target = self.resolve_path(page_id=page_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(raw_bytes)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target)
            temp_path = None
        except OSError as exc:
            if temp_path is not None:
                _remove_owned_file(temp_path)
            raise ConfluenceRawPageStoreError(
                "raw page publication failed"
            ) from exc

        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        _verify_persisted_bytes(target=target, expected=raw_bytes)
        return RawPageArtifact(
            path=target,
            raw_sha256=raw_sha256,
            byte_count=len(raw_bytes),
        )


def _require_page_id(value: object) -> str:
    return require_confluence_page_id(value)


def _resolve_without_requiring_existence(path: Path) -> Path:
    # The raw tree may not exist yet; resolve the parent (strict=False) and
    # rejoin the filename so `..` segments are collapsed for the containment
    # check without needing the file on disk.
    return path.parent.resolve().joinpath(path.name)


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _verify_persisted_bytes(*, target: Path, expected: bytes) -> None:
    try:
        persisted = target.read_bytes()
    except OSError as exc:
        raise ConfluenceRawPageStoreError(
            "raw page could not be read back for verification"
        ) from exc
    if persisted != expected:
        raise ConfluenceRawPageStoreError(
            "persisted raw page bytes did not match the fetched bytes"
        )


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
