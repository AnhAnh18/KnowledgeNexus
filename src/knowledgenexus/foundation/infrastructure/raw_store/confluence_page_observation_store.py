from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
)
from knowledgenexus.foundation.domain.models.raw_observation_artifact import (
    RawObservationArtifact,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawObservationStoreError,
    RawObservationStorePort,
    RawPageReadError,
    RawPageReadPort,
)


class ConfluenceRawPageReadError(RawPageReadError):
    """The deterministic M6A page artifact could not be read."""


class ConfluenceRawObservationStoreError(RawObservationStoreError):
    """A deterministic M6B observation artifact could not be published."""


class ConfluencePageObservationStore(RawPageReadPort, RawObservationStorePort):
    """Reads M6A input and atomically replaces exact M6B response artifacts."""

    def __init__(self, *, raw_root: Path) -> None:
        if not isinstance(raw_root, Path):
            raise TypeError("raw_root expects a pathlib.Path")
        self._raw_root = raw_root

    def read_page(self, *, page_id: str) -> bytes:
        page_id = require_confluence_page_id(page_id)
        target = self._resolve(
            "confluence", "pages", f"{page_id}.json"
        )
        try:
            if not target.is_file():
                raise ConfluenceRawPageReadError("raw page artifact is unavailable")
            return target.read_bytes()
        except ConfluenceRawPageReadError:
            raise
        except OSError as exc:
            raise ConfluenceRawPageReadError(
                "raw page artifact could not be read"
            ) from exc

    def write_restriction(
        self,
        *,
        selected_page_id: str,
        target_page_id: str,
        raw_bytes: bytes,
    ) -> RawObservationArtifact:
        selected_page_id = require_confluence_page_id(selected_page_id)
        target_page_id = require_confluence_page_id(target_page_id)
        target = self._resolve(
            "confluence",
            "restrictions",
            "view",
            selected_page_id,
            f"{target_page_id}.body",
        )
        return self._write(target=target, raw_bytes=raw_bytes)

    def write_attachment_window(
        self,
        *,
        selected_page_id: str,
        request: AttachmentMetadataRequest,
        raw_bytes: bytes,
    ) -> RawObservationArtifact:
        selected_page_id = require_confluence_page_id(selected_page_id)
        if not isinstance(request, AttachmentMetadataRequest):
            raise TypeError("request expects AttachmentMetadataRequest")
        target = self._resolve(
            "confluence",
            "attachments",
            "metadata",
            selected_page_id,
            f"start-{request.start}_limit-{request.limit}.json",
        )
        return self._write(target=target, raw_bytes=raw_bytes)

    def _resolve(self, *parts: str) -> Path:
        resolved_root = self._raw_root.resolve()
        target = resolved_root.joinpath(*parts)
        resolved_target = target.parent.resolve().joinpath(target.name)
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ConfluenceRawObservationStoreError(
                "resolved observation path escapes the raw root"
            ) from exc
        return resolved_target

    def _write(self, *, target: Path, raw_bytes: bytes) -> RawObservationArtifact:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("raw_bytes expects bytes")
        temp_path: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
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
            raise ConfluenceRawObservationStoreError(
                "raw observation publication failed"
            ) from exc

        try:
            persisted = target.read_bytes()
        except OSError as exc:
            raise ConfluenceRawObservationStoreError(
                "raw observation could not be verified"
            ) from exc
        if persisted != raw_bytes:
            raise ConfluenceRawObservationStoreError(
                "raw observation verification failed"
            )
        return RawObservationArtifact(
            path=target,
            raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            byte_count=len(raw_bytes),
        )


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
