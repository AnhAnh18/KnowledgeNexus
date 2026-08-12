from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import threading
from pathlib import Path, PosixPath, WindowsPath

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentPublicationOutcome,
    MediaAttachmentRawArtifact,
    MediaBodyStoreBudget,
)
from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _bound_stat,
    _is_link_or_reparse,
    _metadata,
    _open_bound_parent,
    _posix_open_regular,
    _windows_open_regular_fd,
)
from knowledgenexus.foundation.ports.confluence_raw_attachment_store_port import (
    ConfluenceRawAttachmentStoreError,
    ConfluenceRawAttachmentStoreFailureCategory,
    ConfluenceRawAttachmentStorePort,
)


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_ATTACHMENTS_SUBDIR = ("confluence", "attachments")
_READ_CHUNK_BYTES = 64 * 1024
_MAX_READ_OVERHEAD = 1 * 1024 * 1024
_MAX_SCAN_DEPTH = 128
_MAX_SCAN_ENTRIES = 1_000_000
_PATH_TYPES = (PosixPath, WindowsPath)
_PUBLISH_LOCKS: dict[Path, threading.Lock] = {}
_PUBLISH_LOCKS_GUARD = threading.Lock()


def _fail(category: str | ConfluenceRawAttachmentStoreFailureCategory) -> None:
    try:
        normalized = (
            category
            if isinstance(category, ConfluenceRawAttachmentStoreFailureCategory)
            else ConfluenceRawAttachmentStoreFailureCategory(category)
        )
    except (TypeError, ValueError):
        normalized = ConfluenceRawAttachmentStoreFailureCategory.RAW_ARTIFACT_INVALID
    raise ConfluenceRawAttachmentStoreError(normalized) from None


def _require_plain_directory_chain(path: Path) -> None:
    try:
        chain = [*path.parents, path]
        chain.reverse()
    except Exception:
        _fail("raw_artifact_invalid")
    for component in chain:
        try:
            details = os.lstat(component)
        except Exception:
            _fail("raw_artifact_invalid")
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            _fail("raw_artifact_invalid")


def _require_attachment_id(value: object) -> str:
    if type(value) is not str:
        _fail("raw_artifact_invalid")
    try:
        return require_confluence_attachment_id(value)
    except (TypeError, ValueError):
        _fail("raw_artifact_invalid")


def _require_hash(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail("raw_artifact_invalid")
    return value


def _entry_size(details: os.stat_result) -> int:
    if (
        _is_link_or_reparse(details)
        or not stat.S_ISREG(details.st_mode)
        or getattr(details, "st_nlink", 1) != 1
    ):
        _fail("raw_artifact_invalid")
    if type(details.st_size) is not int or details.st_size < 0:
        _fail("raw_artifact_invalid")
    return details.st_size


def _directory_identity(path: Path) -> tuple[int, int, int]:
    try:
        details = os.lstat(path)
    except Exception:
        _fail("raw_artifact_invalid")
    if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        _fail("raw_artifact_invalid")
    return (details.st_dev, details.st_ino, details.st_mode)


def _handle_directory_identity(handle: int) -> tuple[int, int, int]:
    try:
        details = os.fstat(handle)
    except Exception:
        _fail("raw_artifact_invalid")
    if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
        _fail("raw_artifact_invalid")
    return (details.st_dev, details.st_ino, details.st_mode)


def _scan_tree(path: Path) -> int:
    """Count regular bytes while rejecting unsafe or changing entries."""

    total = 0
    pending: list[tuple[Path, int]] = [(path, 0)]
    entry_count = 0
    while pending:
        current, depth = pending.pop()
        try:
            root_details = os.lstat(current)
        except FileNotFoundError:
            if current == path:
                return 0
            _fail("raw_artifact_invalid")
        except Exception:
            _fail("raw_artifact_invalid")
        if _is_link_or_reparse(root_details) or not stat.S_ISDIR(root_details.st_mode):
            _fail("raw_artifact_invalid")
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > _MAX_SCAN_ENTRIES:
                        _fail("raw_artifact_invalid")
                    entry_path = Path(entry.path)
                    try:
                        before = os.lstat(entry_path)
                    except Exception:
                        _fail("raw_artifact_invalid")
                    if _is_link_or_reparse(before):
                        _fail("raw_artifact_invalid")
                    if stat.S_ISDIR(before.st_mode):
                        if depth >= _MAX_SCAN_DEPTH:
                            _fail("raw_artifact_invalid")
                        pending.append((entry_path, depth + 1))
                        continue
                    total += _entry_size(before)
                    try:
                        after = os.lstat(entry_path)
                    except Exception:
                        _fail("raw_artifact_invalid")
                    if _metadata(after) != _metadata(before):
                        _fail("raw_artifact_invalid")
        except ConfluenceRawAttachmentStoreError:
            raise
        except Exception:
            _fail("raw_artifact_invalid")
        try:
            after_root = os.lstat(current)
        except Exception:
            _fail("raw_artifact_invalid")
        if (
            _is_link_or_reparse(after_root)
            or not stat.S_ISDIR(after_root.st_mode)
            or _metadata(after_root) != _metadata(root_details)
        ):
            _fail("raw_artifact_invalid")
    return total


def _publish_lock_for(data_root: Path) -> threading.Lock:
    with _PUBLISH_LOCKS_GUARD:
        lock = _PUBLISH_LOCKS.get(data_root)
        if lock is None:
            lock = threading.Lock()
            _PUBLISH_LOCKS[data_root] = lock
        return lock


def _read_bound_limited(parent_handle: int, name: str, *, max_bytes: int) -> bytes:
    descriptor = (
        _windows_open_regular_fd(parent_handle, name)
        if os.name == "nt"
        else _posix_open_regular(parent_handle, name)
    )
    try:
        before = os.fstat(descriptor)
        if (
            _is_link_or_reparse(before)
            or not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_nlink", 1) != 1
        ):
            raise OSError("unsafe regular entry")
        if before.st_size > max_bytes:
            raise OverflowError("bounded read exceeded")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after_descriptor = os.fstat(descriptor)
        after_path = _bound_stat(parent_handle, name)
        content = b"".join(chunks)
        if (
            len(content) > max_bytes
            or _metadata(after_descriptor) != _metadata(before)
            or _metadata(after_path) != _metadata(before)
        ):
            raise OSError("unstable regular entry")
        return content
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


class ConfluenceRawAttachmentStore(ConfluenceRawAttachmentStorePort):
    """Immutable, deterministic raw attachment envelope store."""

    def __init__(self, *, data_root: Path, budget: MediaBodyStoreBudget) -> None:
        # WindowsPath/POSIXPath are the concrete pathlib.Path types returned
        # by the platform, so the boundary accepts those concrete subclasses.
        if type(data_root) not in _PATH_TYPES:
            _fail("raw_artifact_invalid")
        try:
            is_absolute = data_root.is_absolute()
            parts = data_root.parts
        except Exception:
            _fail("raw_artifact_invalid")
        if not is_absolute:
            _fail("raw_artifact_invalid")
        if any(part in {".", ".."} for part in parts):
            _fail("raw_artifact_invalid")
        if type(budget) is not MediaBodyStoreBudget:
            _fail("raw_artifact_invalid")
        try:
            validated_budget = MediaBodyStoreBudget(
                max_body_bytes=budget.max_body_bytes,
                max_total_bytes=budget.max_total_bytes,
                minimum_free_disk_reserve_bytes=budget.minimum_free_disk_reserve_bytes,
            )
        except Exception:
            _fail("raw_artifact_invalid")
        _require_plain_directory_chain(data_root)
        try:
            canonical_root = data_root.resolve(strict=True)
        except Exception:
            _fail("raw_artifact_invalid")
        self._data_root = data_root
        self._data_root_identity = _directory_identity(data_root)
        self._budget = validated_budget
        self._publish_lock = _publish_lock_for(canonical_root)

    def resolve_attachment_path(self, *, attachment_id: str, content_hash: str) -> Path:
        attachment = _require_attachment_id(attachment_id)
        digest = _require_hash(content_hash)
        target = self._data_root.joinpath(
            *_ATTACHMENTS_SUBDIR,
            attachment,
            f"{digest}.json",
        )
        try:
            target.relative_to(self._data_root)
        except ValueError:
            _fail("raw_artifact_invalid")
        return target

    def publish_attachment(
        self, *, envelope: MediaAttachmentBodyEnvelope
    ) -> MediaAttachmentRawArtifact:
        with self._publish_lock:
            return self._publish_attachment(envelope=envelope)

    def _publish_attachment(
        self, *, envelope: MediaAttachmentBodyEnvelope
    ) -> MediaAttachmentRawArtifact:
        envelope = self._revalidate_envelope(envelope)
        if type(envelope) is not MediaAttachmentBodyEnvelope:
            _fail("raw_artifact_invalid")
        body = envelope.body_bytes
        if type(body) is not bytes or len(body) > self._budget.max_body_bytes:
            _fail("budget_exceeded")
        try:
            content = envelope.to_bytes()
        except (TypeError, ValueError, OverflowError):
            _fail("raw_artifact_invalid")
        if type(content) is not bytes:
            _fail("raw_artifact_invalid")
        try:
            target = self.resolve_attachment_path(
                attachment_id=envelope.attachment_id,
                content_hash=hashlib.sha256(body).hexdigest(),
            )
        except ConfluenceRawAttachmentStoreError:
            raise
        except Exception:
            _fail("raw_artifact_invalid")
        serialized_size = len(content)
        if serialized_size > self._budget.max_total_bytes:
            _fail("budget_exceeded")

        # Scan before replay so unsafe sibling or temporary entries are never
        # hidden by an otherwise valid existing target.
        self._assert_data_root_identity()
        try:
            existing_bytes = _scan_tree(self._data_root.joinpath(*_ATTACHMENTS_SUBDIR))
        except ConfluenceRawAttachmentStoreError:
            raise
        except Exception:
            _fail("raw_artifact_invalid")
        self._assert_data_root_identity()
        existing = self._read_existing(target)
        if existing is not None:
            return self._replay_or_conflict(
                target=target,
                existing=existing,
                expected=content,
                envelope=envelope,
            )

        if existing_bytes + serialized_size > self._budget.max_total_bytes:
            _fail("budget_exceeded")
        try:
            disk_free = shutil.disk_usage(self._data_root).free
        except Exception:
            _fail("budget_exceeded")
        if type(disk_free) is not int or disk_free < (
            serialized_size + self._budget.minimum_free_disk_reserve_bytes
        ):
            _fail("budget_exceeded")

        self._ensure_target_parent(target.parent)
        expected_parent_identity = _directory_identity(target.parent)
        self._assert_data_root_identity()
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                parent_identity = (
                    _directory_identity(target.parent)
                    if os.name == "nt"
                    else _handle_directory_identity(parent_handle)
                )
                if parent_identity != expected_parent_identity:
                    _fail("raw_artifact_invalid")
                published = self._publish_bound(
                    parent_handle=parent_handle,
                    target_name=target.name,
                    content=content,
                )
            if not published:
                raced = self._read_existing(target)
                if raced is None:
                    _fail("raw_publication_failure")
                return self._replay_or_conflict(
                    target=target,
                    existing=raced,
                    expected=content,
                    envelope=envelope,
                )
            persisted = self._read_existing(target)
            if persisted != content:
                _fail("raw_publication_failure")
            return self._artifact(
                target=target,
                envelope=envelope,
                outcome=MediaAttachmentPublicationOutcome.PUBLISHED,
            )
        except ConfluenceRawAttachmentStoreError:
            raise
        except OverflowError:
            _fail("raw_artifact_invalid")
        except (OSError, TypeError, ValueError):
            _fail("raw_publication_failure")
        except Exception:
            _fail("raw_publication_failure")

    def _assert_data_root_identity(self) -> None:
        if _directory_identity(self._data_root) != self._data_root_identity:
            _fail("raw_artifact_invalid")

    def read_attachment(
        self, *, attachment_id: str, content_hash: str
    ) -> MediaAttachmentBodyEnvelope:
        attachment = _require_attachment_id(attachment_id)
        digest = _require_hash(content_hash)
        target = self.resolve_attachment_path(
            attachment_id=attachment,
            content_hash=digest,
        )
        content = self._read_existing(target)
        if content is None:
            _fail("raw_artifact_invalid")
        envelope = self._parse(content)
        if (
            envelope.attachment_id != attachment
            or hashlib.sha256(envelope.body_bytes).hexdigest() != digest
        ):
            _fail("raw_artifact_invalid")
        return envelope

    @staticmethod
    def _revalidate_envelope(value: object) -> MediaAttachmentBodyEnvelope:
        if type(value) is not MediaAttachmentBodyEnvelope:
            _fail("raw_artifact_invalid")
        try:
            return MediaAttachmentBodyEnvelope(
                format_version=value.format_version,
                evidence_kind=value.evidence_kind,
                attachment_id=value.attachment_id,
                parent_page_id=value.parent_page_id,
                filename=value.filename,
                source_version=value.source_version,
                http_status=value.http_status,
                body_encoding=value.body_encoding,
                body_bytes=value.body_bytes,
            )
        except Exception:
            _fail("raw_artifact_invalid")

    def _ensure_target_parent(self, parent: Path) -> None:
        try:
            parent.relative_to(self._data_root)
        except ValueError:
            _fail("raw_artifact_invalid")
        try:
            with _open_bound_parent(parent, create=True):
                pass
        except Exception:
            _fail("raw_artifact_invalid")

    def _read_existing(self, target: Path) -> bytes | None:
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                try:
                    details = _bound_stat(parent_handle, target.name)
                except FileNotFoundError:
                    return None
                if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode):
                    _fail("raw_artifact_invalid")
                return _read_bound_limited(
                    parent_handle,
                    target.name,
                    max_bytes=max(16 * 1024 * 1024, self._budget.max_body_bytes * 2 + _MAX_READ_OVERHEAD),
                )
        except ConfluenceRawAttachmentStoreError:
            raise
        except FileNotFoundError:
            return None
        except OverflowError:
            _fail("raw_artifact_invalid")
        except Exception:
            _fail("raw_artifact_invalid")

    def _parse(self, content: bytes) -> MediaAttachmentBodyEnvelope:
        try:
            envelope = MediaAttachmentBodyEnvelope.from_bytes(content)
            canonical = envelope.to_bytes()
        except (TypeError, ValueError, OverflowError):
            _fail("raw_artifact_invalid")
        except Exception:
            _fail("raw_artifact_invalid")
        if canonical != content:
            _fail("raw_artifact_invalid")
        return envelope

    def _replay_or_conflict(
        self,
        *,
        target: Path,
        existing: bytes,
        expected: bytes,
        envelope: MediaAttachmentBodyEnvelope,
    ) -> MediaAttachmentRawArtifact:
        self._parse(existing)
        if existing != expected:
            _fail("raw_replay_conflict")
        return self._artifact(
            target=target,
            envelope=envelope,
            outcome=MediaAttachmentPublicationOutcome.REUSED,
        )

    @staticmethod
    def _artifact(
        *,
        target: Path,
        envelope: MediaAttachmentBodyEnvelope,
        outcome: MediaAttachmentPublicationOutcome,
    ) -> MediaAttachmentRawArtifact:
        digest = hashlib.sha256(envelope.body_bytes).hexdigest()
        return MediaAttachmentRawArtifact(
            path=target,
            attachment_id=envelope.attachment_id,
            body_sha256=digest,
            byte_count=len(envelope.body_bytes),
            raw_uri=f"raw://confluence/attachments/{envelope.attachment_id}/{digest}",
            outcome=outcome,
        )

    @staticmethod
    def _publish_bound(*, parent_handle: int, target_name: str, content: bytes) -> bool:
        # Keep the no-clobber primitive local so publication never falls back
        # to check-then-write semantics.
        from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
            _publish_bound,
        )

        return _publish_bound(parent_handle, target_name, content)


__all__ = ["ConfluenceRawAttachmentStore"]
