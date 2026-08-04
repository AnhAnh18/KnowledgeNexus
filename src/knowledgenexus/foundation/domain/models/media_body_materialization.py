from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PosixPath, WindowsPath

from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_RFC3339 = re.compile(
    r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?:[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.[0-9]+)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_MIME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SOURCE_VERSION = re.compile(r"^[^\x00-\x1f\x7f-\x9f]{1,256}$")
_MEDIA_ID = re.compile(r"^confluence:attachment:(?:att)?[0-9]+$")
_PAGE_DOCUMENT_ID = re.compile(r"^confluence:page:[0-9]+$")
_ASSET_FIELDS = frozenset(
    {
        "schema_version",
        "media_id",
        "parent_document_id",
        "source_system",
        "filename",
        "mime_type",
        "size_bytes",
        "download_status",
        "processing_status",
        "relevance",
        "extracted_text",
        "summary",
        "confidence",
        "raw_uri",
        "content_hash",
        "source_version",
        "updated_at",
        "crawled_at",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "format_version",
        "evidence_kind",
        "attachment_id",
        "parent_page_id",
        "filename",
        "source_version",
        "http_status",
        "body_encoding",
        "body_base64",
        "body_byte_count",
        "body_sha256",
    }
)
_MAX_BODY_BYTES = 256 * 1024 * 1024
_PATH_TYPES = (PosixPath, WindowsPath)


def _validate_timestamp(value: object, field_name: str) -> str:
    if type(value) is not str or _RFC3339.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field_name} is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _validate_filename(value: object) -> str:
    if type(value) is not str:
        raise TypeError("filename is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 512
        or "/" in normalized
        or "\\" in normalized
        or any(
            ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            or character in ("\u2028", "\u2029")
            for character in normalized
        )
    ):
        raise ValueError("filename is invalid")
    return normalized


def _validate_mime(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("mime_type is invalid")
    normalized = value.strip().lower()
    if _MIME.fullmatch(normalized) is None or len(normalized.encode("utf-8")) > 256:
        raise ValueError("mime_type is invalid")
    return normalized


def _validate_source_version(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or _SOURCE_VERSION.fullmatch(value) is None
        or len(value.encode("utf-8")) > 256
        or any(character in value for character in ("\r", "\n", "\u2028", "\u2029"))
    ):
        raise ValueError("source_version is invalid")
    return value


def _validate_attachment_id(value: object) -> str:
    if type(value) is not str:
        raise TypeError("attachment_id is invalid")
    try:
        return require_confluence_attachment_id(value)
    except (TypeError, ValueError):
        raise ValueError("attachment_id is invalid") from None


def _validate_page_id(value: object) -> str:
    if type(value) is not str:
        raise TypeError("parent_page_id is invalid")
    try:
        return require_confluence_page_id(value)
    except (TypeError, ValueError):
        raise ValueError("parent_page_id is invalid") from None


class MediaBodyMaterializationFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_OBSERVATION = "invalid_observation"
    INVALID_POLICY = "invalid_policy"
    FETCH = "fetch"
    RESPONSE_SIZE_LIMIT = "response_size_limit"
    HTTP = "http"
    METADATA_MISMATCH = "metadata_mismatch"
    BUDGET_EXCEEDED = "budget_exceeded"
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"
    RAW_REPLAY_CONFLICT = "raw_replay_conflict"
    RAW_PUBLICATION_FAILURE = "raw_publication_failure"
    SCHEMA_INVALID = "schema_invalid"
    INTERNAL_FAILURE = "internal_failure"


class MediaBodyMaterializationError(Exception):
    """Sanitized failure from the attachment body boundary."""

    def __init__(self, category: MediaBodyMaterializationFailureCategory) -> None:
        if not isinstance(category, MediaBodyMaterializationFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        try:
            category = self.category.value
        except Exception:
            return f"{type(self).__name__}()"
        return f"{type(self).__name__}(category={category!r})"


@dataclass(frozen=True, repr=False)
class MediaBodyStoreBudget:
    max_body_bytes: int
    max_total_bytes: int
    minimum_free_disk_reserve_bytes: int

    def __post_init__(self) -> None:
        for value in (
            self.max_body_bytes,
            self.max_total_bytes,
            self.minimum_free_disk_reserve_bytes,
        ):
            if type(value) is not int:
                raise TypeError("budget values are invalid")
        if not 0 < self.max_body_bytes <= _MAX_BODY_BYTES:
            raise ValueError("max_body_bytes is invalid")
        if self.max_total_bytes < self.max_body_bytes:
            raise ValueError("max_total_bytes is invalid")
        if self.minimum_free_disk_reserve_bytes < 0:
            raise ValueError("minimum_free_disk_reserve_bytes is invalid")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class MediaAttachmentBodyEnvelope:
    format_version: str
    evidence_kind: str
    attachment_id: str
    parent_page_id: str
    filename: str
    source_version: str | None
    http_status: int
    body_encoding: str
    body_bytes: bytes

    def __post_init__(self) -> None:
        if (
            type(self.format_version) is not str
            or type(self.evidence_kind) is not str
            or self.format_version != "1"
            or self.evidence_kind != "confluence_attachment_body"
        ):
            raise ValueError("envelope identity is invalid")
        if type(self.body_encoding) is not str or self.body_encoding != "base64":
            raise ValueError("body encoding is invalid")
        if type(self.http_status) is not int or self.http_status != 200:
            raise ValueError("http status is invalid")
        object.__setattr__(self, "attachment_id", _validate_attachment_id(self.attachment_id))
        object.__setattr__(self, "parent_page_id", _validate_page_id(self.parent_page_id))
        object.__setattr__(self, "filename", _validate_filename(self.filename))
        object.__setattr__(self, "source_version", _validate_source_version(self.source_version))
        if type(self.body_bytes) is not bytes:
            raise TypeError("body bytes are invalid")

    def to_bytes(self) -> bytes:
        payload = {
            "attachment_id": self.attachment_id,
            "body_base64": base64.b64encode(self.body_bytes).decode("ascii"),
            "body_byte_count": len(self.body_bytes),
            "body_encoding": self.body_encoding,
            "body_sha256": hashlib.sha256(self.body_bytes).hexdigest(),
            "evidence_kind": self.evidence_kind,
            "filename": self.filename,
            "format_version": self.format_version,
            "http_status": self.http_status,
            "parent_page_id": self.parent_page_id,
            "source_version": self.source_version,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, serialized: bytes) -> "MediaAttachmentBodyEnvelope":
        if type(serialized) is not bytes:
            raise TypeError("serialized envelope is invalid")

        def reject_constant(_value: str) -> None:
            raise ValueError("serialized envelope is invalid")

        def reject_duplicate(pairs: list[tuple[object, object]]) -> dict[object, object]:
            output: dict[object, object] = {}
            for key, value in pairs:
                if key in output:
                    raise ValueError("serialized envelope is invalid")
                output[key] = value
            return output

        try:
            payload = json.loads(
                serialized.decode("utf-8"),
                object_pairs_hook=reject_duplicate,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ValueError("serialized envelope is invalid") from None
        if not isinstance(payload, dict) or set(payload) != _ENVELOPE_FIELDS:
            raise ValueError("serialized envelope is invalid")
        encoded = payload["body_base64"]
        if type(encoded) is not str:
            raise ValueError("serialized envelope is invalid")
        try:
            encoded_bytes = encoded.encode("ascii")
            body = base64.b64decode(encoded_bytes, validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            raise ValueError("serialized envelope is invalid") from None
        if base64.b64encode(body) != encoded_bytes:
            raise ValueError("serialized envelope is invalid")
        count = payload["body_byte_count"]
        digest = payload["body_sha256"]
        if (
            type(count) is not int
            or count < 0
            or count != len(body)
            or type(digest) is not str
            or _SHA256.fullmatch(digest) is None
            or digest != hashlib.sha256(body).hexdigest()
        ):
            raise ValueError("serialized envelope is invalid")
        try:
            envelope = cls(
                format_version=payload["format_version"],
                evidence_kind=payload["evidence_kind"],
                attachment_id=payload["attachment_id"],
                parent_page_id=payload["parent_page_id"],
                filename=payload["filename"],
                source_version=payload["source_version"],
                http_status=payload["http_status"],
                body_encoding=payload["body_encoding"],
                body_bytes=body,
            )
        except (TypeError, ValueError):
            raise ValueError("serialized envelope is invalid") from None
        if envelope.to_bytes() != serialized:
            raise ValueError("serialized envelope is invalid")
        return envelope

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class MediaAttachmentPublicationOutcome(StrEnum):
    PUBLISHED = "published"
    REUSED = "reused"


@dataclass(frozen=True, repr=False)
class MediaAttachmentRawArtifact:
    path: Path
    attachment_id: str
    body_sha256: str
    byte_count: int
    raw_uri: str
    outcome: MediaAttachmentPublicationOutcome

    def __post_init__(self) -> None:
        if type(self.path) not in _PATH_TYPES or not self.path.is_absolute():
            raise TypeError("path is invalid")
        object.__setattr__(self, "attachment_id", _validate_attachment_id(self.attachment_id))
        if type(self.body_sha256) is not str or _SHA256.fullmatch(self.body_sha256) is None:
            raise ValueError("body_sha256 is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("byte_count is invalid")
        expected_uri = (
            f"raw://confluence/attachments/{self.attachment_id}/{self.body_sha256}"
        )
        if type(self.raw_uri) is not str or self.raw_uri != expected_uri:
            raise ValueError("raw_uri is invalid")
        if not isinstance(self.outcome, MediaAttachmentPublicationOutcome):
            raise TypeError("outcome is invalid")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class MediaBodyMaterializationResult:
    asset: dict[str, object]
    artifact: MediaAttachmentRawArtifact

    def __post_init__(self) -> None:
        if type(self.asset) is not dict or type(self.artifact) is not MediaAttachmentRawArtifact:
            raise TypeError("media body result is invalid")
        try:
            artifact = MediaAttachmentRawArtifact(
                path=self.artifact.path,
                attachment_id=self.artifact.attachment_id,
                body_sha256=self.artifact.body_sha256,
                byte_count=self.artifact.byte_count,
                raw_uri=self.artifact.raw_uri,
                outcome=self.artifact.outcome,
            )
        except Exception:
            raise ValueError("media body result is invalid") from None
        object.__setattr__(self, "artifact", artifact)
        if set(self.asset) != _ASSET_FIELDS:
            raise ValueError("asset fields are invalid")
        copied = dict(self.asset)
        for key, value in copied.items():
            if type(key) is not str or type(value) not in {str, int, float, bool, type(None)}:
                raise TypeError("asset values are invalid")
        if (
            copied["schema_version"] != "1.0"
            or copied["source_system"] != "confluence"
            or copied["download_status"] != "downloaded"
            or copied["processing_status"] != "not_processed"
            or copied["relevance"] != "high"
            or any(copied[field] is not None for field in ("extracted_text", "summary", "confidence"))
        ):
            raise ValueError("asset status is invalid")
        attachment_id = _validate_attachment_id(artifact.attachment_id)
        if copied["media_id"] != f"confluence:attachment:{attachment_id}":
            raise ValueError("asset identity is invalid")
        if copied["raw_uri"] != artifact.raw_uri or copied["content_hash"] != artifact.body_sha256:
            raise ValueError("asset evidence is invalid")
        if type(copied["parent_document_id"]) is not str or _PAGE_DOCUMENT_ID.fullmatch(copied["parent_document_id"]) is None:
            raise ValueError("asset parent identity is invalid")
        _validate_filename(copied["filename"])
        _validate_mime(copied["mime_type"])
        size = copied["size_bytes"]
        if size is not None and (type(size) is not int or size < 0 or size != artifact.byte_count):
            raise ValueError("asset size is invalid")
        if type(copied["content_hash"]) is not str or _SHA256.fullmatch(copied["content_hash"]) is None:
            raise ValueError("asset content hash is invalid")
        _validate_source_version(copied["source_version"])
        if copied["updated_at"] is not None:
            _validate_timestamp(copied["updated_at"], "updated_at")
        _validate_timestamp(copied["crawled_at"], "crawled_at")
        object.__setattr__(self, "asset", copied)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


__all__ = [
    "MediaAttachmentBodyEnvelope",
    "MediaAttachmentPublicationOutcome",
    "MediaAttachmentRawArtifact",
    "MediaBodyMaterializationError",
    "MediaBodyMaterializationFailureCategory",
    "MediaBodyMaterializationResult",
    "MediaBodyStoreBudget",
]
