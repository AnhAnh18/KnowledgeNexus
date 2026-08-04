from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Self

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)

M7_RAW_PAGE_FORMAT_VERSION: Final = "1"
M7_RAW_PAGE_EVIDENCE_KIND: Final = "confluence_raw_page"
M7_RAW_PAGE_REQUEST_KIND: Final = "page_body"
M7_RAW_PAGE_REQUEST_PROFILE_VERSION: Final = "m7-confluence-request-profile-v1"
M7_RAW_PAGE_BODY_ENCODING: Final = "base64"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "body_base64",
        "body_byte_count",
        "body_encoding",
        "body_sha256",
        "evidence_kind",
        "format_version",
        "generation_id",
        "http_status",
        "page_id",
        "request_kind",
        "request_profile_version",
        "run_id",
        "source_version",
    }
)


class ConfluenceRawPageEvidenceFailureCategory(StrEnum):
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"


class ConfluenceRawPageEvidenceError(Exception):
    """Sanitized failure for invalid M7 raw-page evidence."""

    def __init__(
        self,
        category: ConfluenceRawPageEvidenceFailureCategory =
        ConfluenceRawPageEvidenceFailureCategory.RAW_ARTIFACT_INVALID,
    ) -> None:
        if not isinstance(category, ConfluenceRawPageEvidenceFailureCategory):
            raise TypeError("category expects ConfluenceRawPageEvidenceFailureCategory")
        self.category = category
        super().__init__(category.value)


class ConfluenceRawPagePublicationOutcome(StrEnum):
    PUBLISHED = "published"
    REUSED = "reused"


class ConfluenceRawPageStoreFailureCategory(StrEnum):
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"
    RAW_IDENTITY_MISMATCH = "raw_identity_mismatch"
    RAW_REPLAY_CONFLICT = "raw_replay_conflict"
    RAW_PUBLICATION_FAILURE = "raw_publication_failure"


def _invalid() -> None:
    raise ConfluenceRawPageEvidenceError() from None


def _reject_constant(_value: str) -> None:
    _invalid()


def _reject_duplicate_keys(pairs: list[tuple[object, object]]) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _strict_body_base64(value: object) -> bytes:
    if not isinstance(value, str):
        _invalid()
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        _invalid()
    if base64.b64encode(decoded) != encoded:
        _invalid()
    return decoded


def _validated_run_id(value: object) -> CrawlRunId:
    if type(value) is not CrawlRunId:
        _invalid()
    try:
        rebuilt = CrawlRunId(value.value)
    except Exception:
        _invalid()
    if rebuilt != value:
        _invalid()
    return rebuilt


def _validated_source_version(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 256:
        _invalid()
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _invalid()
    return value


@dataclass(frozen=True, repr=False)
class ConfluenceRawPageEnvelope:
    """Canonical exact-byte evidence for one generation-scoped raw page."""

    request_profile_version: str
    run_id: CrawlRunId
    generation_id: CrawlRunId
    page_id: str
    source_version: str | None
    http_status: int
    body_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.request_profile_version != M7_RAW_PAGE_REQUEST_PROFILE_VERSION:
            raise ValueError("request profile version is invalid")
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId:
            raise TypeError("run and generation ids are invalid")
        if self.run_id != self.generation_id:
            raise ValueError("run and generation ids must match")
        try:
            rebuilt_run = CrawlRunId(self.run_id.value)
            rebuilt_generation = CrawlRunId(self.generation_id.value)
            page_id = require_confluence_page_id(self.page_id)
        except (TypeError, ValueError):
            raise ValueError("raw page identity is invalid") from None
        if rebuilt_run != self.run_id or rebuilt_generation != self.generation_id:
            raise ValueError("raw page identity is invalid")
        if isinstance(self.http_status, bool) or type(self.http_status) is not int:
            raise TypeError("http status is invalid")
        if not 100 <= self.http_status <= 599:
            raise ValueError("http status is invalid")
        if type(self.body_bytes) is not bytes:
            raise TypeError("body bytes are invalid")
        if self.source_version is not None:
            _validated_source_version(self.source_version)
        object.__setattr__(self, "request_profile_version", M7_RAW_PAGE_REQUEST_PROFILE_VERSION)
        object.__setattr__(self, "run_id", rebuilt_run)
        object.__setattr__(self, "generation_id", rebuilt_generation)
        object.__setattr__(self, "page_id", page_id)

    @classmethod
    def capture(
        cls,
        *,
        run_id: CrawlRunId,
        page_id: str,
        source_version: str | None,
        http_status: int,
        body_bytes: bytes,
        request_profile_version: str = M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
    ) -> Self:
        return cls(
            request_profile_version=request_profile_version,
            run_id=run_id,
            generation_id=run_id,
            page_id=page_id,
            source_version=source_version,
            http_status=http_status,
            body_bytes=body_bytes,
        )

    def to_bytes(self) -> bytes:
        body_base64 = base64.b64encode(self.body_bytes).decode("ascii")
        payload = {
            "body_base64": body_base64,
            "body_byte_count": len(self.body_bytes),
            "body_encoding": M7_RAW_PAGE_BODY_ENCODING,
            "body_sha256": hashlib.sha256(self.body_bytes).hexdigest(),
            "evidence_kind": M7_RAW_PAGE_EVIDENCE_KIND,
            "format_version": M7_RAW_PAGE_FORMAT_VERSION,
            "generation_id": str(self.generation_id),
            "http_status": self.http_status,
            "page_id": self.page_id,
            "request_kind": M7_RAW_PAGE_REQUEST_KIND,
            "request_profile_version": self.request_profile_version,
            "run_id": str(self.run_id),
            "source_version": self.source_version,
        }
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, OverflowError):
            _invalid()

    @classmethod
    def from_bytes(cls, serialized: bytes) -> Self:
        if type(serialized) is not bytes:
            _invalid()
        try:
            payload = json.loads(
                serialized.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            _invalid()
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            _invalid()
        body_bytes = _strict_body_base64(payload["body_base64"])
        body_count = payload["body_byte_count"]
        body_sha256 = payload["body_sha256"]
        if (
            isinstance(body_count, bool)
            or type(body_count) is not int
            or body_count < 0
            or body_count != len(body_bytes)
            or not isinstance(body_sha256, str)
            or _SHA256.fullmatch(body_sha256) is None
            or body_sha256 != hashlib.sha256(body_bytes).hexdigest()
        ):
            _invalid()
        if (
            payload["format_version"] != M7_RAW_PAGE_FORMAT_VERSION
            or payload["evidence_kind"] != M7_RAW_PAGE_EVIDENCE_KIND
            or payload["request_kind"] != M7_RAW_PAGE_REQUEST_KIND
            or payload["body_encoding"] != M7_RAW_PAGE_BODY_ENCODING
            or payload["request_profile_version"] != M7_RAW_PAGE_REQUEST_PROFILE_VERSION
        ):
            _invalid()
        try:
            run_id = CrawlRunId(payload["run_id"])
            generation_id = CrawlRunId(payload["generation_id"])
        except (TypeError, ValueError):
            _invalid()
        try:
            envelope = cls(
                request_profile_version=payload["request_profile_version"],
                run_id=run_id,
                generation_id=generation_id,
                page_id=payload["page_id"],
                source_version=payload["source_version"],
                http_status=payload["http_status"],
                body_bytes=body_bytes,
            )
        except Exception:
            _invalid()
        if envelope.to_bytes() != serialized:
            _invalid()
        return envelope

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ConfluenceRawPageArtifact:
    """Sanitized metadata for one published generation-scoped raw page."""

    path: Path
    run_id: CrawlRunId
    page_id: str
    raw_sha256: str
    byte_count: int
    outcome: ConfluenceRawPagePublicationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise TypeError("path expects an absolute pathlib.Path")
        if type(self.run_id) is not CrawlRunId:
            raise TypeError("run_id expects CrawlRunId")
        try:
            page_id = require_confluence_page_id(self.page_id)
        except (TypeError, ValueError):
            raise ValueError("page_id is invalid") from None
        if not isinstance(self.raw_sha256, str) or _SHA256.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("byte_count is invalid")
        if not isinstance(self.outcome, ConfluenceRawPagePublicationOutcome):
            raise TypeError("outcome is invalid")
        object.__setattr__(self, "page_id", page_id)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"(outcome={self.outcome.value!r}, byte_count={self.byte_count})"
        )


__all__ = [
    "ConfluenceRawPageArtifact",
    "ConfluenceRawPageEvidenceError",
    "ConfluenceRawPageEvidenceFailureCategory",
    "ConfluenceRawPageEnvelope",
    "ConfluenceRawPagePublicationOutcome",
    "ConfluenceRawPageStoreFailureCategory",
    "M7_RAW_PAGE_BODY_ENCODING",
    "M7_RAW_PAGE_EVIDENCE_KIND",
    "M7_RAW_PAGE_FORMAT_VERSION",
    "M7_RAW_PAGE_REQUEST_KIND",
    "M7_RAW_PAGE_REQUEST_PROFILE_VERSION",
]
