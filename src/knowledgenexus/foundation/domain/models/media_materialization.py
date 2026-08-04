from __future__ import annotations

import re
import unicodedata
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


_RFC3339 = re.compile(
    r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?:[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.[0-9]+)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_MIME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_MEDIA_ID = re.compile(r"^confluence:attachment:(?:att)?[0-9]+$")
_PAGE_DOCUMENT_ID = re.compile(r"^confluence:page:[0-9]+$")
_SOURCE_VERSION = re.compile(r"^[^\x00-\x1f\x7f-\x9f]{1,256}$")
_FILENAME_MAX_BYTES = 512
_EVIDENCE_MAX_BYTES = 512
_POLICIES = frozenset({"metadata_only", "skip", "download_and_process"})
_MEDIA_ASSET_FIELDS = frozenset(
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


def _validate_optional_source_version(value: object) -> str | None:
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


def _validate_filename(value: object) -> str:
    if type(value) is not str:
        raise TypeError("filename is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > _FILENAME_MAX_BYTES
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


def _validate_size(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > (2**63 - 1):
        raise ValueError("size_bytes is invalid")
    return value


def _validate_evidence(value: object) -> str:
    if type(value) is not str:
        raise TypeError("evidence is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > _EVIDENCE_MAX_BYTES
        or any(
            ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            or character in ("\u2028", "\u2029")
            for character in normalized
        )
    ):
        raise ValueError("evidence is invalid")
    return normalized


class MediaMaterializationFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_OBSERVATION = "invalid_observation"
    INVALID_POLICY = "invalid_policy"
    INVALID_INTENT = "invalid_intent"
    SCHEMA_INVALID = "schema_invalid"
    DUPLICATE_ID = "duplicate_id"
    CROSS_PAGE = "cross_page"
    POLICY_CONFLICT = "policy_conflict"
    INTERNAL_FAILURE = "internal_failure"


class MediaMaterializationError(Exception):
    """Sanitized failure for the pure media materialization boundary."""

    def __init__(self, category: MediaMaterializationFailureCategory) -> None:
        if not isinstance(category, MediaMaterializationFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category!r})"


@dataclass(frozen=True, repr=False)
class ConfluenceAttachmentObservation:
    attachment_id: str
    parent_page_id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    source_version: str | None = None
    updated_at: str | None = None
    crawled_at: str = ""

    def __post_init__(self) -> None:
        if type(self.attachment_id) is not str:
            raise TypeError("attachment_id is invalid")
        try:
            attachment_id = require_confluence_attachment_id(self.attachment_id)
        except (TypeError, ValueError):
            raise ValueError("attachment_id is invalid") from None
        if type(self.parent_page_id) is not str:
            raise TypeError("parent_page_id is invalid")
        try:
            parent_page_id = require_confluence_page_id(self.parent_page_id)
        except (TypeError, ValueError):
            raise ValueError("parent_page_id is invalid") from None
        object.__setattr__(self, "attachment_id", attachment_id)
        object.__setattr__(self, "parent_page_id", parent_page_id)
        object.__setattr__(self, "filename", _validate_filename(self.filename))
        object.__setattr__(self, "mime_type", _validate_mime(self.mime_type))
        object.__setattr__(self, "size_bytes", _validate_size(self.size_bytes))
        object.__setattr__(
            self,
            "source_version",
            _validate_optional_source_version(self.source_version),
        )
        if self.updated_at is not None:
            _validate_timestamp(self.updated_at, "updated_at")
        object.__setattr__(self, "crawled_at", _validate_timestamp(self.crawled_at, "crawled_at"))


@dataclass(frozen=True, repr=False)
class MediaPolicyDecision:
    attachment_id: str
    policy: str

    def __post_init__(self) -> None:
        if type(self.attachment_id) is not str:
            raise TypeError("attachment_id is invalid")
        try:
            attachment_id = require_confluence_attachment_id(self.attachment_id)
        except (TypeError, ValueError):
            raise ValueError("attachment_id is invalid") from None
        if type(self.policy) is not str or self.policy not in _POLICIES:
            raise ValueError("policy is invalid")
        object.__setattr__(self, "attachment_id", attachment_id)


@dataclass(frozen=True, repr=False)
class MediaRelationIntent:
    ordinal: int
    source_document_id: str
    target_media_id: str | None
    intent_kind: str
    relation_type: str
    resolution_status: str
    evidence: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError("ordinal is invalid")
        if type(self.source_document_id) is not str or _PAGE_DOCUMENT_ID.fullmatch(self.source_document_id) is None:
            raise ValueError("source_document_id is invalid")
        if self.target_media_id is not None:
            if type(self.target_media_id) is not str or _MEDIA_ID.fullmatch(self.target_media_id) is None:
                raise ValueError("target_media_id is invalid")
        if type(self.intent_kind) is not str or self.intent_kind not in {"drawio", "image_attachment"}:
            raise ValueError("intent_kind is invalid")
        if type(self.relation_type) is not str or self.relation_type != "embeds_media":
            raise ValueError("relation_type is invalid")
        if type(self.resolution_status) is not str or self.resolution_status != "unresolved_target":
            raise ValueError("resolution_status is invalid")
        object.__setattr__(self, "evidence", _validate_evidence(self.evidence))


@dataclass(frozen=True, repr=False)
class MediaMaterializationResult:
    assets: tuple[dict[str, object], ...]
    relation_intents: tuple[MediaRelationIntent, ...]

    def __post_init__(self) -> None:
        if type(self.assets) is not tuple or any(type(record) is not dict for record in self.assets):
            raise TypeError("assets are invalid")
        if type(self.relation_intents) is not tuple or any(
            type(intent) is not MediaRelationIntent for intent in self.relation_intents
        ):
            raise TypeError("relation_intents are invalid")
        validated_intents: list[MediaRelationIntent] = []
        for intent in self.relation_intents:
            try:
                validated_intents.append(
                    MediaRelationIntent(
                        ordinal=intent.ordinal,
                        source_document_id=intent.source_document_id,
                        target_media_id=intent.target_media_id,
                        intent_kind=intent.intent_kind,
                        relation_type=intent.relation_type,
                        resolution_status=intent.resolution_status,
                        evidence=intent.evidence,
                    )
                )
            except Exception:
                raise TypeError("relation_intents are invalid") from None
        copied_assets: list[dict[str, object]] = []
        seen_media_ids: set[str] = set()
        for record in self.assets:
            if set(record) != _MEDIA_ASSET_FIELDS:
                raise ValueError("asset fields are invalid")
            copied: dict[str, object] = {}
            for key, value in record.items():
                if type(key) is not str or type(value) not in {str, int, float, bool, type(None)}:
                    raise TypeError("asset values are invalid")
                if type(value) is float and not math.isfinite(value):
                    raise ValueError("asset values are invalid")
                copied[key] = value
            if copied["schema_version"] != "1.0" or copied["source_system"] != "confluence":
                raise ValueError("asset identity is invalid")
            if type(copied["media_id"]) is not str or _MEDIA_ID.fullmatch(copied["media_id"]) is None:
                raise ValueError("asset IDs are invalid")
            if type(copied["parent_document_id"]) is not str or _PAGE_DOCUMENT_ID.fullmatch(copied["parent_document_id"]) is None:
                raise ValueError("asset parent identity is invalid")
            copied["filename"] = _validate_filename(copied["filename"])
            copied["mime_type"] = _validate_mime(copied["mime_type"])
            _validate_size(copied["size_bytes"])
            if (copied["download_status"], copied["processing_status"], copied["relevance"]) not in {
                ("skipped", "not_processed", "unknown"),
                ("skipped", "not_processed", "low"),
                ("not_attempted", "not_processed", "high"),
            }:
                raise ValueError("asset status combination is invalid")
            for field in ("extracted_text", "summary", "confidence", "raw_uri", "content_hash"):
                if copied[field] is not None:
                    raise ValueError("asset processing evidence is invalid")
            _validate_optional_source_version(copied["source_version"])
            if copied["updated_at"] is not None:
                _validate_timestamp(copied["updated_at"], "updated_at")
            _validate_timestamp(copied["crawled_at"], "crawled_at")
            media_id = copied.get("media_id")
            if type(media_id) is not str or media_id in seen_media_ids:
                raise ValueError("asset IDs are invalid")
            seen_media_ids.add(media_id)
            copied_assets.append(copied)
        ordinals = tuple(intent.ordinal for intent in validated_intents)
        if ordinals != tuple(range(1, len(ordinals) + 1)):
            raise ValueError("relation ordinals are invalid")
        seen_relation_keys: set[tuple[str, str, str]] = set()
        for intent in validated_intents:
            key = (intent.source_document_id, intent.intent_kind, intent.evidence)
            if key in seen_relation_keys:
                raise ValueError("relation identities are duplicated")
            seen_relation_keys.add(key)
        media_ids = tuple(record["media_id"] for record in copied_assets)
        if media_ids != tuple(sorted(media_ids)):
            raise ValueError("asset ordering is invalid")
        parent_document_ids = {record["parent_document_id"] for record in copied_assets}
        if len(parent_document_ids) > 1 and validated_intents:
            raise ValueError("cross-page relation state is invalid")
        for intent in validated_intents:
            if intent.source_document_id not in parent_document_ids:
                raise ValueError("relation source is not represented")
            if intent.target_media_id is not None and intent.target_media_id not in seen_media_ids:
                raise ValueError("relation target is not represented")
        object.__setattr__(self, "assets", tuple(copied_assets))
        object.__setattr__(self, "relation_intents", tuple(validated_intents))


__all__ = [
    "ConfluenceAttachmentObservation",
    "MediaMaterializationError",
    "MediaMaterializationFailureCategory",
    "MediaMaterializationResult",
    "MediaPolicyDecision",
    "MediaRelationIntent",
]
