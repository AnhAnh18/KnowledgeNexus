from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
    ParsedAttachmentMetadataWindow,
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


class ConfluencePageObservationPayloadError(ValueError):
    """A sanitized failure while validating page-adjacent payloads."""


def extract_ordered_restriction_targets(
    *, raw_page: bytes, selected_page_id: str
) -> tuple[str, ...]:
    """Validate an M6A page and return ancestors followed by the page itself."""
    selected_page_id = require_confluence_page_id(selected_page_id)
    payload = _decode_object(raw_page, category="raw page")
    observed_id = payload.get("id")
    if isinstance(observed_id, bool) or not isinstance(observed_id, (str, int)):
        raise ConfluencePageObservationPayloadError("raw page identity is invalid")
    if str(observed_id) != selected_page_id:
        raise ConfluencePageObservationPayloadError("raw page identity does not match")

    ancestors = payload.get("ancestors")
    if not isinstance(ancestors, list):
        raise ConfluencePageObservationPayloadError("raw page ancestors must be a list")

    ordered: list[str] = []
    seen: set[str] = set()
    for ancestor in ancestors:
        if not isinstance(ancestor, Mapping):
            raise ConfluencePageObservationPayloadError("raw page ancestor is invalid")
        try:
            ancestor_id = _coerce_page_id(ancestor.get("id"))
        except (TypeError, ValueError) as exc:
            raise ConfluencePageObservationPayloadError(
                "raw page ancestor identity is invalid"
            ) from exc
        if ancestor_id == selected_page_id:
            raise ConfluencePageObservationPayloadError(
                "raw page contains self ancestry"
            )
        if ancestor_id in seen:
            raise ConfluencePageObservationPayloadError(
                "raw page contains duplicate ancestry"
            )
        seen.add(ancestor_id)
        ordered.append(ancestor_id)
    ordered.append(selected_page_id)
    return tuple(ordered)


def build_restriction_observation(
    *, target_page_id: str, response: RawHttpObservation
) -> dict[str, object]:
    """Normalize one view-restriction response without deriving effective ACL."""
    target_page_id = require_confluence_page_id(target_page_id)
    base: dict[str, object] = {
        "source_page_id": target_page_id,
        "http_status": response.status_code,
        "classification": "unavailable",
        "users": [],
        "groups": [],
    }
    if response.status_code in (401, 403, 404):
        return base
    if response.status_code != 200:
        raise ConfluencePageObservationPayloadError(
            "restriction response status is unsupported"
        )

    try:
        payload = _decode_object(response.body, category="restriction response")
        if payload.get("operation") != "view":
            raise ConfluencePageObservationPayloadError(
                "restriction operation is unrecognized"
            )
        restrictions = payload.get("restrictions")
        if not isinstance(restrictions, Mapping):
            raise ConfluencePageObservationPayloadError(
                "restriction principal envelope is invalid"
            )
        users = _principal_identifiers(
            restrictions.get("user"), kind="user", allowed=("username", "userKey", "accountId")
        )
        groups = _principal_identifiers(
            restrictions.get("group"), kind="group", allowed=("name",)
        )
    except (ConfluencePageObservationPayloadError, TypeError, ValueError):
        return base

    base["users"] = users
    base["groups"] = groups
    base["classification"] = "restricted" if users or groups else "unrestricted"
    return base


def parse_attachment_metadata_window(
    *,
    raw_bytes: bytes,
    selected_page_id: str,
    request: AttachmentMetadataRequest,
) -> ParsedAttachmentMetadataWindow:
    """Parse one exact attachment window and validate its observed next link."""
    selected_page_id = require_confluence_page_id(selected_page_id)
    payload = _decode_object(raw_bytes, category="attachment response")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ConfluencePageObservationPayloadError(
            "attachment response results must be a list"
        )

    attachments: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for item in results:
        attachment = _build_attachment_observation(
            item=item, selected_page_id=selected_page_id
        )
        attachment_id = attachment["attachment_id"]
        assert isinstance(attachment_id, str)
        if attachment_id in seen_ids:
            raise ConfluencePageObservationPayloadError(
                "attachment response contains duplicate identities"
            )
        seen_ids.add(attachment_id)
        attachments.append(attachment)

    next_request = _extract_next_attachment_request(
        payload=payload,
        selected_page_id=selected_page_id,
        current=request,
    )
    return ParsedAttachmentMetadataWindow(
        attachments=tuple(attachments),
        next_request=next_request,
    )


def _decode_object(raw_bytes: object, *, category: str) -> Mapping[str, object]:
    if not isinstance(raw_bytes, bytes):
        raise TypeError("raw_bytes expects bytes")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConfluencePageObservationPayloadError(
            f"{category} is not valid JSON"
        ) from None
    if not isinstance(payload, Mapping):
        raise ConfluencePageObservationPayloadError(
            f"{category} must be a JSON object"
        )
    return payload


def _coerce_page_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError("page id is invalid")
    return require_confluence_page_id(str(value))


def _principal_identifiers(
    envelope: object, *, kind: str, allowed: tuple[str, ...]
) -> list[dict[str, str]]:
    if not isinstance(envelope, Mapping):
        raise ConfluencePageObservationPayloadError(
            "restriction principal collection is invalid"
        )
    results = envelope.get("results")
    if not isinstance(results, list):
        raise ConfluencePageObservationPayloadError(
            "restriction principal results are invalid"
        )
    normalized: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for principal in results:
        if not isinstance(principal, Mapping):
            raise ConfluencePageObservationPayloadError(
                "restriction principal is invalid"
            )
        identifiers: dict[str, str] = {}
        for name in allowed:
            value = principal.get(name)
            if value is not None:
                if not isinstance(value, str) or value == "":
                    raise ConfluencePageObservationPayloadError(
                        "restriction principal identifier is invalid"
                    )
                identifiers[name] = value
        if not identifiers:
            raise ConfluencePageObservationPayloadError(
                f"restriction {kind} identifier is unrecognized"
            )
        identity = tuple(identifiers.items())
        if identity in seen:
            raise ConfluencePageObservationPayloadError(
                "restriction principal identity is duplicated"
            )
        seen.add(identity)
        normalized.append(identifiers)
    return normalized


def _build_attachment_observation(
    *, item: object, selected_page_id: str
) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise ConfluencePageObservationPayloadError("attachment entry is invalid")
    try:
        attachment_id = _coerce_attachment_id(item.get("id"))
    except (TypeError, ValueError) as exc:
        raise ConfluencePageObservationPayloadError(
            "attachment identity is invalid"
        ) from exc
    title = item.get("title")
    if not isinstance(title, str):
        raise ConfluencePageObservationPayloadError("attachment title is invalid")
    item_type = item.get("type")
    if item_type is not None and item_type != "attachment":
        raise ConfluencePageObservationPayloadError("attachment type is invalid")

    observation: dict[str, object] = {
        "source_page_id": selected_page_id,
        "attachment_id": attachment_id,
        "filename": title,
    }
    _copy_optional_string(item, "status", observation, "status")
    metadata = item.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise ConfluencePageObservationPayloadError(
                "attachment metadata is invalid"
            )
        _copy_optional_string(metadata, "mediaType", observation, "media_type")
    extensions = item.get("extensions")
    if extensions is not None:
        if not isinstance(extensions, Mapping):
            raise ConfluencePageObservationPayloadError(
                "attachment extensions are invalid"
            )
        file_size = extensions.get("fileSize")
        if file_size is not None:
            if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0:
                raise ConfluencePageObservationPayloadError(
                    "attachment file size is invalid"
                )
            observation["file_size"] = file_size
    version = item.get("version")
    if version is not None:
        if not isinstance(version, Mapping):
            raise ConfluencePageObservationPayloadError(
                "attachment version is invalid"
            )
        number = version.get("number")
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ConfluencePageObservationPayloadError(
                    "attachment version number is invalid"
                )
            observation["version_number"] = number
    return observation


def _coerce_attachment_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError("attachment id is invalid")
    return require_confluence_attachment_id(str(value))


def _copy_optional_string(
    source: Mapping[str, object],
    source_key: str,
    target: dict[str, object],
    target_key: str,
) -> None:
    value = source.get(source_key)
    if value is None:
        return
    if not isinstance(value, str):
        raise ConfluencePageObservationPayloadError(
            "attachment metadata string is invalid"
        )
    target[target_key] = value


def _extract_next_attachment_request(
    *,
    payload: Mapping[str, object],
    selected_page_id: str,
    current: AttachmentMetadataRequest,
) -> AttachmentMetadataRequest | None:
    if "_links" not in payload:
        return None
    links = payload["_links"]
    if not isinstance(links, Mapping):
        raise ConfluencePageObservationPayloadError("attachment links are invalid")
    if "next" not in links:
        return None
    next_link = links["next"]
    if not isinstance(next_link, str) or next_link == "":
        raise ConfluencePageObservationPayloadError(
            "attachment next link is invalid"
        )
    if any(character.isspace() or ord(character) < 32 for character in next_link):
        raise ConfluencePageObservationPayloadError(
            "attachment next link is invalid"
        )
    parsed = urllib.parse.urlsplit(next_link)
    expected_path = f"/rest/api/content/{selected_page_id}/child/attachment"
    if (
        parsed.scheme != ""
        or parsed.netloc != ""
        or parsed.fragment != ""
        or parsed.path != expected_path
    ):
        raise ConfluencePageObservationPayloadError(
            "attachment next link is outside the expected endpoint"
        )
    try:
        query = urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        raise ConfluencePageObservationPayloadError(
            "attachment next link query is invalid"
        ) from None
    if set(query) != {"start", "limit"} or any(len(values) != 1 for values in query.values()):
        raise ConfluencePageObservationPayloadError(
            "attachment next link query is invalid"
        )
    try:
        start = _parse_canonical_non_negative_int(query["start"][0], name="start")
        limit = _parse_canonical_positive_int(query["limit"][0], name="limit")
        next_request = AttachmentMetadataRequest(start=start, limit=limit)
    except (TypeError, ValueError) as exc:
        raise ConfluencePageObservationPayloadError(
            "attachment next link window is invalid"
        ) from exc
    if next_request == current:
        raise ConfluencePageObservationPayloadError(
            "attachment next link does not advance"
        )
    return next_request


def _parse_canonical_non_negative_int(value: str, *, name: str) -> int:
    if value == "0":
        return 0
    if not value.isascii() or not value.isdigit() or value.startswith("0"):
        raise ValueError(f"{name} is invalid")
    return int(value)


def _parse_canonical_positive_int(value: str, *, name: str) -> int:
    parsed = _parse_canonical_non_negative_int(value, name=name)
    if parsed <= 0:
        raise ValueError(f"{name} is invalid")
    return parsed
