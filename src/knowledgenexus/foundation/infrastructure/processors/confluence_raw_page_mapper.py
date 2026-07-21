from __future__ import annotations

import json
from collections.abc import Mapping

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageSource,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMapperPort,
    ConfluenceRawPageMappingError,
)


class ConfluenceDataCenterRawPageMapper(ConfluenceRawPageMapperPort):
    """Extract trusted M6C inputs from one exact M6A page response."""

    def map_page(
        self,
        *,
        raw_bytes: bytes,
        expected_page_id: str,
    ) -> ConfluencePageSource:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("raw_bytes expects bytes")
        try:
            expected_page_id = require_confluence_page_id(expected_page_id)
        except (TypeError, ValueError) as exc:
            raise ConfluenceRawPageMappingError(
                "expected page identity is invalid"
            ) from exc

        payload = _decode_object(raw_bytes)
        page_id = _require_page_identity(payload, expected_page_id)
        if "type" in payload and payload.get("type") != "page":
            raise ConfluenceRawPageMappingError(
                "page response.type must equal 'page'"
            )

        title = _require_non_empty_string(payload, "title", "page response.title")
        space = _require_mapping(payload, "space", "page response.space")
        space_key = _require_non_empty_string(
            space,
            "key",
            "page response.space.key",
        )
        version = _require_mapping(payload, "version", "page response.version")
        version_number = version.get("number")
        if (
            isinstance(version_number, bool)
            or not isinstance(version_number, int)
            or version_number <= 0
        ):
            raise ConfluenceRawPageMappingError(
                "page response.version.number must be a positive integer"
            )
        updated_at = _require_non_empty_string(
            version,
            "when",
            "page response.version.when",
        )

        body = _require_mapping(payload, "body", "page response.body")
        storage = _require_mapping(body, "storage", "page response.body.storage")
        storage_xhtml = _require_string(
            storage,
            "value",
            "page response.body.storage.value",
        )
        if storage.get("representation") != "storage":
            raise ConfluenceRawPageMappingError(
                "page response.body.storage.representation must equal 'storage'"
            )

        return ConfluencePageSource(
            page_id=page_id,
            title=title,
            space_key=space_key,
            source_version=str(version_number),
            updated_at=updated_at,
            storage_xhtml=storage_xhtml,
        )


def _decode_object(raw_bytes: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfluenceRawPageMappingError(
            "raw page must be valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ConfluenceRawPageMappingError("raw page JSON must be an object")
    return payload


def _require_page_identity(
    payload: Mapping[str, object],
    expected_page_id: str,
) -> str:
    value = payload.get("id")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ConfluenceRawPageMappingError("page response.id is invalid")
    observed = str(value)
    try:
        observed = require_confluence_page_id(observed)
    except (TypeError, ValueError) as exc:
        raise ConfluenceRawPageMappingError("page response.id is invalid") from exc
    if observed != expected_page_id:
        raise ConfluenceRawPageMappingError("page response identity does not match")
    return observed


def _require_mapping(
    parent: Mapping[str, object],
    key: str,
    field_path: str,
) -> Mapping[str, object]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ConfluenceRawPageMappingError(f"{field_path} must be an object")
    return value


def _require_string(
    parent: Mapping[str, object],
    key: str,
    field_path: str,
) -> str:
    value = parent.get(key)
    if not isinstance(value, str):
        raise ConfluenceRawPageMappingError(f"{field_path} must be a string")
    return value


def _require_non_empty_string(
    parent: Mapping[str, object],
    key: str,
    field_path: str,
) -> str:
    value = _require_string(parent, key, field_path)
    if value.strip() == "":
        raise ConfluenceRawPageMappingError(f"{field_path} must not be empty")
    return value
