from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)

M7_RESTRICTION_REQUEST_PROFILE_VERSION: Final = "m7-confluence-request-profile-v1"
M7_RESTRICTION_FORMAT_VERSION: Final = "1"
M7_RESTRICTION_EVIDENCE_KIND: Final = "confluence_restriction_observation"
M7_RESTRICTION_REQUEST_KIND: Final = "view_restriction"
M7_RESTRICTION_BODY_ENCODING: Final = "base64"
_COMPLETED_STATUSES = frozenset({200, 401, 403, 404})
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "format_version",
        "evidence_kind",
        "request_kind",
        "request_profile_version",
        "selected_page_id",
        "target_page_id",
        "http_status",
        "body_encoding",
        "body_base64",
        "body_byte_count",
        "body_sha256",
    }
)


class ConfluenceRestrictionEvidenceFailureCategory(StrEnum):
    RAW_ARTIFACT_INVALID = "raw_artifact_invalid"


class ConfluenceRestrictionEvidenceError(Exception):
    """Sanitized failure for invalid M7 restriction evidence."""

    def __init__(
        self,
        category: ConfluenceRestrictionEvidenceFailureCategory =
        ConfluenceRestrictionEvidenceFailureCategory.RAW_ARTIFACT_INVALID,
    ) -> None:
        if not isinstance(category, ConfluenceRestrictionEvidenceFailureCategory):
            raise TypeError("category expects ConfluenceRestrictionEvidenceFailureCategory")
        self.category = category
        super().__init__(category.value)


def _invalid() -> None:
    raise ConfluenceRestrictionEvidenceError() from None


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


def _validate_identity(
    *,
    request_profile_version: object,
    selected_page_id: object,
    target_page_id: object,
    http_status: object,
    body_bytes: object,
) -> tuple[str, str, str, int, bytes]:
    if request_profile_version != M7_RESTRICTION_REQUEST_PROFILE_VERSION:
        _invalid()
    if not isinstance(request_profile_version, str):
        _invalid()
    try:
        selected = require_confluence_page_id(selected_page_id)
        target = require_confluence_page_id(target_page_id)
    except (TypeError, ValueError):
        _invalid()
    if isinstance(http_status, bool) or type(http_status) is not int:
        _invalid()
    if http_status not in _COMPLETED_STATUSES:
        _invalid()
    if type(body_bytes) is not bytes:
        _invalid()
    return request_profile_version, selected, target, http_status, body_bytes


@dataclass(frozen=True, repr=False)
class ConfluenceRestrictionEvidenceEnvelope:
    """Canonical, exact-byte M7 restriction observation evidence."""

    request_profile_version: str
    selected_page_id: str
    target_page_id: str
    http_status: int
    body_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        values = _validate_identity(
            request_profile_version=self.request_profile_version,
            selected_page_id=self.selected_page_id,
            target_page_id=self.target_page_id,
            http_status=self.http_status,
            body_bytes=self.body_bytes,
        )
        object.__setattr__(self, "request_profile_version", values[0])
        object.__setattr__(self, "selected_page_id", values[1])
        object.__setattr__(self, "target_page_id", values[2])
        object.__setattr__(self, "http_status", values[3])
        object.__setattr__(self, "body_bytes", values[4])

    @classmethod
    def capture(
        cls,
        *,
        request_profile_version: str,
        selected_page_id: str,
        target_page_id: str,
        http_status: int,
        body_bytes: bytes,
    ) -> Self:
        return cls(
            request_profile_version=request_profile_version,
            selected_page_id=selected_page_id,
            target_page_id=target_page_id,
            http_status=http_status,
            body_bytes=body_bytes,
        )

    def to_bytes(self) -> bytes:
        body_base64 = base64.b64encode(self.body_bytes).decode("ascii")
        payload = {
            "body_base64": body_base64,
            "body_byte_count": len(self.body_bytes),
            "body_encoding": M7_RESTRICTION_BODY_ENCODING,
            "body_sha256": hashlib.sha256(self.body_bytes).hexdigest(),
            "evidence_kind": M7_RESTRICTION_EVIDENCE_KIND,
            "format_version": M7_RESTRICTION_FORMAT_VERSION,
            "http_status": self.http_status,
            "request_kind": M7_RESTRICTION_REQUEST_KIND,
            "request_profile_version": self.request_profile_version,
            "selected_page_id": self.selected_page_id,
            "target_page_id": self.target_page_id,
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
            text = serialized.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            _invalid()
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            _invalid()

        body_bytes = _strict_body_base64(payload["body_base64"])
        body_byte_count = payload["body_byte_count"]
        body_sha256 = payload["body_sha256"]
        if (
            isinstance(body_byte_count, bool)
            or type(body_byte_count) is not int
            or body_byte_count < 0
            or body_byte_count != len(body_bytes)
            or not isinstance(body_sha256, str)
            or _SHA256.fullmatch(body_sha256) is None
            or body_sha256 != hashlib.sha256(body_bytes).hexdigest()
        ):
            _invalid()
        if (
            payload["format_version"] != M7_RESTRICTION_FORMAT_VERSION
            or payload["evidence_kind"] != M7_RESTRICTION_EVIDENCE_KIND
            or payload["request_kind"] != M7_RESTRICTION_REQUEST_KIND
            or payload["body_encoding"] != M7_RESTRICTION_BODY_ENCODING
        ):
            _invalid()

        envelope = cls.capture(
            request_profile_version=payload["request_profile_version"],
            selected_page_id=payload["selected_page_id"],
            target_page_id=payload["target_page_id"],
            http_status=payload["http_status"],
            body_bytes=body_bytes,
        )
        if envelope.to_bytes() != serialized:
            _invalid()
        return envelope

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
