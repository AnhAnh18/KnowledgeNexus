#!/usr/bin/env python3
"""Collect a sanitized, read-only Confluence API confirmation packet.

This diagnostic is intentionally standalone and standard-library-only. It has
no imports from KnowledgeNexus production packages and never writes raw HTTP
responses. Endpoint and pagination behavior must come from an operator-confirmed
request profile; the script contains no Cloud or Data Center endpoint defaults.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import math
import os
import re
import string
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote_plus,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)
from urllib.request import HTTPRedirectHandler, Request, build_opener


EXIT_OK: Final = 0
EXIT_INPUT: Final = 2
EXIT_CREDENTIAL: Final = 3
EXIT_OUTPUT: Final = 4
EXIT_TRANSPORT: Final = 10
EXIT_HTTP: Final = 11
EXIT_RESPONSE: Final = 12
EXIT_PAGINATION: Final = 13
EXIT_SANITIZATION: Final = 14
EXIT_UNEXPECTED: Final = 70

PROFILE_SCHEMA_VERSION: Final = 1
MAX_RESPONSE_BYTES: Final = 5 * 1024 * 1024
JSON_CONTENT_TYPE_RE: Final = re.compile(
    r"^(?:application|text)/(?:[a-z0-9.+-]*\+)?json(?:\s*;|$)", re.IGNORECASE
)
TIMESTAMP_RE: Final = re.compile(
    r"^(\d{4}-\d{2}-\d{2})([Tt ])(\d{2}:\d{2}:\d{2})"
    r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BEARER_MATERIAL_RE: Final = re.compile(
    r"\bBearer\s+(?!<)[A-Za-z0-9._~+/=-]{6,}", re.IGNORECASE
)
HEADER_LEAK_RE: Final = re.compile(
    r"\b(?:Authorization|Cookie|Set-Cookie)\s*:", re.IGNORECASE
)
BODY_REQUEST_RE: Final = re.compile(
    r"(?:^|[^a-z0-9])body(?:[^a-z0-9]|$)", re.IGNORECASE
)
FORBIDDEN_REQUEST_RESOURCE_RE: Final = re.compile(
    r"(?:^|[^a-z0-9])(?:attachments?|comments?|restrictions?|permissions?|acl|"
    r"rendered(?:html)?|html|viewpage(?:\.action)?|export[_-]?view|"
    r"anonymous[_-]?export[_-]?view|downloads?|exports?)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

ALLOWED_PLACEHOLDERS: Final = frozenset(
    {"root_page_id", "space_key", "page_size"}
)
SAFE_STRING_KEYS: Final = frozenset(
    {
        "type",
        "status",
        "representation",
        "contenttype",
        "mediatype",
        "kind",
        "rel",
    }
)
SAFE_NUMBER_KEYS: Final = frozenset(
    {
        "number",
        "versionnumber",
        "start",
        "limit",
        "size",
        "total",
        "count",
        "attachmentcount",
        "attachment_count",
        "offset",
        "maxresults",
        "resultsperpage",
    }
)
BODY_REPRESENTATION_VALUES: Final = frozenset(
    {
        "storage",
        "view",
        "editor",
        "wiki",
        "plain",
        "raw",
        "atlas_doc_format",
        "export_view",
        "anonymous_export_view",
    }
)
TECHNICAL_ENUM_VALUES: Final = frozenset(
    {
        "page",
        "blogpost",
        "current",
        "draft",
        "archived",
        "historical",
        "next",
        "prev",
        "previous",
        "collection",
        "single",
    }
)
IDENTITY_KEYS: Final = frozenset(
    {
        "accountid",
        "account_id",
        "username",
        "user_name",
        "userkey",
        "user_key",
        "email",
        "emailaddress",
        "displayname",
        "fullname",
        "authorid",
        "author_id",
        "creatorid",
        "creator_id",
        "ownerid",
        "owner_id",
        "userid",
        "user_id",
    }
)
TIMESTAMP_KEYS: Final = frozenset(
    {
        "when",
        "created",
        "createdat",
        "updated",
        "updatedat",
        "modified",
        "lastmodified",
        "timestamp",
    }
)
URL_KEYS: Final = frozenset(
    {"href", "url", "uri", "self", "next", "webui", "tinyui", "base"}
)
PAGE_ID_KEYS: Final = frozenset(
    {
        "id",
        "pageid",
        "page_id",
        "parentid",
        "parent_id",
        "parentpageid",
        "parent_page_id",
        "contentid",
        "content_id",
        "ancestorid",
        "ancestor_id",
    }
)
BODY_CONTEXT_KEYS: Final = frozenset(
    {"body", "storage", "view", "editor", "exportview", "anonymous_export_view"}
)
IDENTITY_CONTEXT_KEYS: Final = frozenset(
    {"user", "users", "person", "people", "author", "creator", "by", "owner"}
)
METADATA_HINT_CONTEXT_KEYS: Final = frozenset(
    {"_expandable", "expandable", "_links", "links", "link"}
)

ALWAYS_PACKET_FILES: Final = frozenset(
    {
        "confluence_api_profile.md",
        "confluence_request_trace.md",
        "root_page_response.sanitized.json",
        "descendants_page_1.sanitized.json",
        "sanitization_report.md",
    }
)


class ProbeError(Exception):
    exit_code = EXIT_UNEXPECTED

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class InputError(ProbeError):
    exit_code = EXIT_INPUT


class CredentialError(ProbeError):
    exit_code = EXIT_CREDENTIAL


class OutputError(ProbeError):
    exit_code = EXIT_OUTPUT


class TransportError(ProbeError):
    exit_code = EXIT_TRANSPORT


class HttpProbeError(ProbeError):
    exit_code = EXIT_HTTP


class ResponseError(ProbeError):
    exit_code = EXIT_RESPONSE


class PaginationError(ProbeError):
    exit_code = EXIT_PAGINATION


class PacketValidationError(ProbeError):
    exit_code = EXIT_SANITIZATION


class SafeArgumentParser(argparse.ArgumentParser):
    """Argparse variant that never echoes unrecognized argument values."""

    def error(self, message: str) -> None:
        option_match = re.search(r"(--[A-Za-z0-9_-]+)", message)
        option = option_match.group(1) if option_match else "command line"
        raise InputError(f"invalid {option}; run with --help")


@dataclass(frozen=True)
class RequestTemplate:
    path_template: str
    query: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PaginationProfile:
    kind: str
    next_pointer: str | None = None
    cursor_query_parameter: str | None = None
    mutable_query_parameters: tuple[str, ...] = ()
    start_query_parameter: str | None = None
    limit_query_parameter: str | None = None
    response_start_pointer: str | None = None
    response_limit_pointer: str | None = None
    response_size_pointer: str | None = None
    response_total_pointer: str | None = None
    terminal_rule: str | None = None


@dataclass(frozen=True)
class RequestProfile:
    deployment: str
    confluence_version: str | None
    api_family: str
    auth_scheme: str
    root_request: RequestTemplate
    inventory_request: RequestTemplate
    pagination: PaginationProfile


@dataclass(frozen=True)
class ProbeConfig:
    profile: RequestProfile
    space_key: str
    root_page_id: str
    page_size: int
    max_pages: int
    timeout_seconds: float
    output_dir: Path


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    content_type: str
    link_header: str | None
    payload: object


@dataclass(frozen=True)
class PaginationDecision:
    mechanism: str
    next_url: str | None
    next_value: str | None
    terminal_condition: str

    @property
    def has_next(self) -> bool:
        return self.next_url is not None


@dataclass(frozen=True)
class RequestObservation:
    sequence: int
    url: str
    status: int
    content_type: str
    link_header: str | None
    pagination_decision: str


@dataclass(frozen=True)
class CollectionResult:
    root: HttpResult
    root_identity: object
    descendant_pages: tuple[HttpResult, ...]
    observations: tuple[RequestObservation, ...]
    pagination_mechanism: str
    next_shapes_observed: tuple[str, ...]
    terminal_condition: str
    pagination_truncated: bool
    terminal_page_observed: bool


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class ReadOnlyHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        authorization_value: str,
        timeout_seconds: float,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self._origin = _origin(self.base_url)
        self._authorization_value = authorization_value
        self._timeout_seconds = timeout_seconds
        self._opener = opener or build_opener(NoRedirectHandler()).open

    def resolve_initial_path(self, path_query: str) -> str:
        parts = urlsplit(path_query)
        if parts.scheme or parts.netloc or parts.fragment:
            raise InputError("request profile paths must be relative and fragment-free")
        if not path_query.startswith("/"):
            raise InputError("request profile paths must start with '/'")
        return f"{self._origin}{path_query}"

    def resolve_next(self, *, current_url: str, next_value: str) -> str:
        if _has_unsafe_text(next_value) or any(
            character.isspace() for character in next_value
        ):
            raise PaginationError("pagination next target contains unsafe text")
        try:
            resolved = urljoin(current_url, next_value)
            parts = urlsplit(resolved)
            if parts.fragment:
                raise PaginationError("pagination next target contains a fragment")
            if _origin(resolved) != self._origin:
                raise PaginationError("pagination next target is cross-origin")
            if parts.scheme != "https":
                raise PaginationError("pagination next target is not HTTPS")
            if parts.username or parts.password:
                raise PaginationError("pagination next target contains userinfo")
            parts.port
        except PaginationError:
            raise
        except (InputError, ValueError) as exc:
            raise PaginationError("pagination next target is malformed") from exc
        return resolved

    def get_json(self, url: str) -> HttpResult:
        if _origin(url) != self._origin:
            raise TransportError("refusing to send credentials cross-origin")
        request = Request(
            url,
            data=None,
            headers={
                "Accept": "application/json",
                "Authorization": self._authorization_value,
                "User-Agent": "KnowledgeNexus-Confluence-Probe/1",
            },
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                status_value = getattr(response, "status", None)
                if status_value is None:
                    status_value = response.getcode()
                status = int(status_value)
                headers = response.headers
                content_type = headers.get("Content-Type", "")
                link_header = headers.get("Link")
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
            raise HttpProbeError(
                f"GET failed with HTTP status {exc.code}; "
                f"Content-Type={_safe_content_type(content_type)}"
            ) from exc
        except URLError as exc:
            raise TransportError("GET failed due to a network or TLS error") from exc
        except TimeoutError as exc:
            raise TransportError("GET timed out") from exc
        except OSError as exc:
            raise TransportError("GET failed due to a local transport error") from exc

        if len(body) > MAX_RESPONSE_BYTES:
            raise ResponseError("JSON response exceeded the in-memory safety limit")
        if not JSON_CONTENT_TYPE_RE.match(content_type.strip()):
            raise ResponseError(
                f"GET returned non-JSON Content-Type={_safe_content_type(content_type)}"
            )
        try:
            payload = _strict_json_loads(body.decode("utf-8-sig"))
            body = b""
            payload = _scrub_body_leaves(payload)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ResponseError(
                f"GET returned invalid JSON; status={status}; "
                f"Content-Type={_safe_content_type(content_type)}"
            ) from exc
        return HttpResult(
            url=url,
            status=status,
            content_type=_safe_content_type(content_type),
            link_header=link_header,
            payload=payload,
        )


def _scrub_body_leaves(
    value: object,
    *,
    key: str | None = None,
    inside_body: bool = False,
) -> object:
    normalized_key = _normalize_key(key)
    in_body = inside_body or normalized_key in BODY_CONTEXT_KEYS
    if isinstance(value, Mapping):
        return {
            str(child_key): _scrub_body_leaves(
                child,
                key=str(child_key),
                inside_body=in_body,
            )
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _scrub_body_leaves(child, key=key, inside_body=in_body)
            for child in value
        ]
    if not in_body or value is None:
        return value
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        return 0.0
    if (
        isinstance(value, str)
        and normalized_key == "representation"
        and value in BODY_REPRESENTATION_VALUES
    ):
        return value
    return "<SANITIZED_BODY>"


class Sanitizer:
    """Default-deny JSON sanitizer with stable typed identity mappings."""

    def __init__(
        self,
        *,
        base_url: str,
        root_page_id: object,
        space_key: str,
        safe_path_segments: Iterable[str] = (),
        safe_query_values: Iterable[tuple[str, str]] = (),
        cursor_keys: Iterable[str] = (),
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._real_hostname = urlsplit(self._base_url).hostname or ""
        self._root_page_id = root_page_id
        self._space_key = space_key
        self._safe_path_segments = frozenset(safe_path_segments)
        self._safe_query_values = frozenset(safe_query_values)
        self._cursor_keys = frozenset(_normalize_key(key) for key in cursor_keys)
        self._page_ids: dict[tuple[type[object], object], object] = {}
        self._titles: dict[str, str] = {}
        self._identities: dict[tuple[type[object], object], object] = {}
        self._numbers: dict[tuple[type[object], object], object] = {}
        self._labels: dict[str, str] = {}
        self._texts: dict[str, str] = {}
        self._cursors: dict[str, str] = {}
        self._query_values: dict[str, str] = {}
        self._path_segments: dict[str, str] = {}
        self._register_page_id(root_page_id)

    def prime(self, value: object) -> None:
        self._prime(value=value, key=None, path=())

    def sanitize(self, value: object) -> object:
        return self._sanitize(value=value, key=None, path=())

    def sanitized_root_id(self) -> object:
        return self._map_page_id(self._root_page_id)

    def sanitize_url(self, value: str) -> str:
        parts = urlsplit(value)
        is_absolute = bool(parts.scheme or parts.netloc)
        path = self._sanitize_url_path(parts.path)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        sanitized_pairs = [
            (key, self._sanitize_query_value(key, raw_value))
            for key, raw_value in query_pairs
        ]
        query = urlencode(sanitized_pairs, doseq=True, safe="<>:_-/\"=()")
        if is_absolute:
            netloc = "<CONFLUENCE_HOST>"
            if parts.port is not None:
                netloc += f":{parts.port}"
            return urlunsplit((parts.scheme, netloc, path, query, ""))
        return urlunsplit(("", "", path, query, ""))

    def sanitize_link_header(self, value: str | None) -> str | None:
        if value is None:
            return None
        sanitized_entries: list[str] = []
        for link_url, parameters in _parse_link_header_entries(value):
            raw_rel = _link_relation_value(parameters)
            if raw_rel is not None:
                relation_tokens = []
                for token in raw_rel.split():
                    relation_tokens.append(
                        token
                        if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", token)
                        else "SANITIZED_REL"
                    )
                relation = " ".join(relation_tokens) or "SANITIZED_REL"
            else:
                relation = "NOT_PRESENT"
            sanitized_entries.append(
                f'<{self.sanitize_url(link_url)}>; rel="{relation}"'
            )
        return ", ".join(sanitized_entries) or "<SANITIZED_LINK_HEADER>"

    def _prime(
        self,
        *,
        value: object,
        key: str | None,
        path: tuple[str, ...],
    ) -> None:
        normalized_key = _normalize_key(key)
        if isinstance(value, Mapping):
            for child_key in sorted(value, key=lambda item: str(item)):
                self._prime(
                    value=value[child_key],
                    key=str(child_key),
                    path=(*path, normalized_key),
                )
            return
        if isinstance(value, list):
            for child in value:
                self._prime(value=child, key=key, path=path)
            return
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            if self._is_identity_context(normalized_key, path):
                self._map_identity(value)
            elif self._is_page_id_context(normalized_key, path):
                self._register_page_id(value)
            elif normalized_key == "title":
                self._map_title(str(value))
            elif self._is_label_context(normalized_key, path):
                self._map_label(str(value))
            elif isinstance(value, int) and normalized_key not in SAFE_NUMBER_KEYS:
                self._map_number(value)
        elif isinstance(value, float) and normalized_key not in SAFE_NUMBER_KEYS:
            self._map_number(value)

    def _sanitize(
        self,
        *,
        value: object,
        key: str | None,
        path: tuple[str, ...],
    ) -> object:
        normalized_key = _normalize_key(key)
        next_path = (*path, normalized_key)
        if isinstance(value, Mapping):
            return {
                str(child_key): self._sanitize(
                    value=child_value,
                    key=str(child_key),
                    path=next_path,
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize(value=child, key=key, path=path) for child in value]
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            if self._is_identity_context(normalized_key, path):
                return self._map_identity(value)
            if self._is_page_id_context(normalized_key, path):
                return self._map_page_id(value)
            if normalized_key in SAFE_NUMBER_KEYS:
                return value
            known_page_id = self._lookup_page_id(value)
            return known_page_id if known_page_id is not None else self._map_number(value)
        if isinstance(value, float):
            if normalized_key in SAFE_NUMBER_KEYS:
                return value
            return self._map_number(value)
        if not isinstance(value, str):
            return self._map_text(str(value))

        if self._is_body_context(normalized_key, path):
            if _is_safe_technical_value(normalized_key, value):
                return value
            return "<SANITIZED_BODY>"
        if self._is_identity_context(normalized_key, path):
            return self._map_identity(value)
        if self._is_page_id_context(normalized_key, path):
            return self._map_page_id(value)
        if normalized_key == "title":
            return self._map_title(value)
        if self._is_space_context(normalized_key, path):
            return "SAN"
        if self._is_label_context(normalized_key, path):
            return self._map_label(value)
        if self._is_cursor_key(normalized_key):
            return self._map_cursor(value)
        if self._is_url_context(normalized_key, value):
            return self.sanitize_url(value)
        if normalized_key in TIMESTAMP_KEYS or TIMESTAMP_RE.match(value) or DATE_RE.match(value):
            return _sanitize_timestamp(value)
        if _is_safe_technical_value(normalized_key, value):
            return value
        return self._map_text(value)

    def _sanitize_url_path(self, path: str) -> str:
        sanitized_segments = []
        for segment in path.split("/"):
            if segment == "":
                sanitized_segments.append("")
                continue
            decoded = _url_decode_component(segment)
            mapped = self._lookup_page_id_text(decoded)
            if mapped is not None:
                sanitized_segments.append(quote(str(mapped), safe="<>:_-"))
            elif decoded == self._space_key or unquote_plus(segment) == self._space_key:
                sanitized_segments.append("SAN")
            else:
                decoded_plus = unquote_plus(segment)
                title = self._lookup_path_mapping(
                    decoded,
                    decoded_plus,
                    mappings=self._titles,
                )
                identity = self._lookup_typed_string_mapping(
                    decoded,
                    decoded_plus,
                    mappings=self._identities,
                )
                label = self._lookup_path_mapping(
                    decoded,
                    decoded_plus,
                    mappings=self._labels,
                )
                if title or identity or label:
                    replacement = title or identity or label
                elif decoded in self._safe_path_segments:
                    sanitized_segments.append(segment)
                    continue
                else:
                    replacement = self._map_path_segment(decoded_plus)
                encoder = quote_plus if "+" in segment else quote
                sanitized_segments.append(encoder(str(replacement), safe="<>:_-"))
        return "/".join(sanitized_segments)

    @staticmethod
    def _lookup_path_mapping(
        decoded: str,
        decoded_plus: str,
        *,
        mappings: Mapping[str, str],
    ) -> str | None:
        return mappings.get(decoded) or mappings.get(decoded_plus)

    @staticmethod
    def _lookup_typed_string_mapping(
        decoded: str,
        decoded_plus: str,
        *,
        mappings: Mapping[tuple[type[object], object], object],
    ) -> object | None:
        return mappings.get((str, decoded)) or mappings.get((str, decoded_plus))

    def _sanitize_query_value(self, key: str, value: str) -> str:
        normalized_key = _normalize_key(key)
        if self._is_cursor_key(normalized_key):
            return self._map_cursor(value)
        if normalized_key in {"limit", "start", "offset", "size"} and value.isdigit():
            return value
        if "space" in normalized_key and value == self._space_key:
            return "SAN"
        if self._is_page_id_context(normalized_key, ()):
            mapped = self._lookup_page_id_text(value)
            return str(mapped if mapped is not None else self._map_page_id(value))
        if (
            normalized_key in {"expand", "fields"}
            and (key, value) in self._safe_query_values
        ):
            return value
        return self._map_query_value(value)

    def _register_page_id(self, value: object) -> None:
        typed_key = (type(value), value)
        if typed_key in self._page_ids:
            return
        if any(
            type(raw_id) is not type(value) and str(raw_id) == str(value)
            for (_, raw_id) in self._page_ids
        ):
            raise PacketValidationError(
                "the same page identity appeared with inconsistent JSON types"
            )
        index = len(self._page_ids) + 1
        if type(value) is int:
            self._page_ids[typed_key] = -100000 - index
        else:
            self._page_ids[typed_key] = f"SANITIZED_PAGE_{index:03d}"

    def _map_page_id(self, value: object) -> object:
        self._register_page_id(value)
        return self._page_ids[(type(value), value)]

    def _lookup_page_id(self, value: object) -> object | None:
        return self._page_ids.get((type(value), value))

    def _lookup_page_id_text(self, value: str) -> object | None:
        exact = self._lookup_page_id(value)
        if exact is not None:
            return exact
        for (_, raw_id), mapped in self._page_ids.items():
            if str(raw_id) == value:
                return mapped
        return None

    def _map_title(self, value: str) -> str:
        if value not in self._titles:
            self._titles[value] = f"Sanitized Page {len(self._titles) + 1:03d}"
        return self._titles[value]

    def _map_identity(self, value: object) -> object:
        typed_key = (type(value), value)
        if typed_key not in self._identities:
            index = len(self._identities) + 1
            if type(value) is int:
                self._identities[typed_key] = -200000 - index
            else:
                self._identities[typed_key] = f"<IDENTITY_{index:03d}>"
        return self._identities[typed_key]

    def _map_number(self, value: object) -> object:
        typed_key = (type(value), value)
        if typed_key not in self._numbers:
            index = len(self._numbers) + 1
            self._numbers[typed_key] = (
                -300000 - index
                if type(value) is int
                else float(-300000 - index)
            )
        return self._numbers[typed_key]

    def _map_label(self, value: str) -> str:
        if value not in self._labels:
            self._labels[value] = f"SANITIZED_LABEL_{len(self._labels) + 1:03d}"
        return self._labels[value]

    def _map_text(self, value: str) -> str:
        if value not in self._texts:
            self._texts[value] = f"<SANITIZED_TEXT_{len(self._texts) + 1:03d}>"
        return self._texts[value]

    def _map_cursor(self, value: str) -> str:
        if value not in self._cursors:
            self._cursors[value] = f"<CURSOR_{len(self._cursors) + 1:03d}>"
        return self._cursors[value]

    def _map_query_value(self, value: str) -> str:
        if value not in self._query_values:
            self._query_values[value] = f"<QUERY_VALUE_{len(self._query_values) + 1:03d}>"
        return self._query_values[value]

    def _map_path_segment(self, value: str) -> str:
        if value not in self._path_segments:
            self._path_segments[value] = f"<PATH_{len(self._path_segments) + 1:03d}>"
        return self._path_segments[value]

    @staticmethod
    def _is_page_id_context(key: str, path: tuple[str, ...]) -> bool:
        if key in PAGE_ID_KEYS:
            return not any(token in IDENTITY_CONTEXT_KEYS for token in path)
        return key in {"ancestors", "ancestorids", "ancestor_page_ids"}

    @staticmethod
    def _is_identity_context(key: str, path: tuple[str, ...]) -> bool:
        identity_suffixes = (
            "accountid",
            "userid",
            "userkey",
            "authorid",
            "creatorid",
            "ownerid",
        )
        compact_key = key.replace("_", "")
        return key in IDENTITY_KEYS or compact_key.endswith(identity_suffixes) or (
            key == "id" and any(token in IDENTITY_CONTEXT_KEYS for token in path)
        )

    @staticmethod
    def _is_body_context(key: str, path: tuple[str, ...]) -> bool:
        return key in BODY_CONTEXT_KEYS or any(token in BODY_CONTEXT_KEYS for token in path)

    @staticmethod
    def _is_space_context(key: str, path: tuple[str, ...]) -> bool:
        return key in {"spacekey", "space_key"} or (
            key in {"key", "name"} and "space" in path
        )

    @staticmethod
    def _is_label_context(key: str, path: tuple[str, ...]) -> bool:
        return key in {"label", "labels"} or "labels" in path

    @staticmethod
    def _is_cursor_context(key: str) -> bool:
        return "cursor" in key or key in {"pagetoken", "page_token", "continuationtoken"}

    def _is_cursor_key(self, key: str) -> bool:
        return key in self._cursor_keys or self._is_cursor_context(key)

    @staticmethod
    def _is_url_context(key: str, value: str) -> bool:
        return key in URL_KEYS or key.endswith("url") or value.startswith(("http://", "https://"))


def build_parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(
        description="Collect a sanitized read-only Confluence API packet",
        allow_abbrev=False,
    )
    parser.add_argument("--request-profile", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-profile-only", action="store_true")
    mode.add_argument("--verify-packet-only", action="store_true")
    parser.add_argument("--space-key")
    parser.add_argument("--root-page-id")
    parser.add_argument("--page-size", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--prompt-scan-identities", action="store_true")
    return parser


def load_request_profile(path: Path) -> RequestProfile:
    try:
        payload = _strict_json_loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError("request profile could not be read") from exc
    except ValueError as exc:
        raise InputError("request profile is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise InputError("request profile must contain one JSON object")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise InputError("request profile schema_version must be 1")

    deployment = _required_choice(payload, "deployment", {"cloud", "data-center"})
    auth_scheme = _required_choice(
        payload,
        "auth_scheme",
        {"bearer_pat", "basic_username_pat"},
    )
    api_family = _required_non_placeholder_string(payload, "api_family")
    version = payload.get("confluence_version")
    if version is not None and (
        not isinstance(version, str)
        or not version
        or _contains_unresolved_marker(version)
        or _has_unsafe_text(version)
    ):
        raise InputError("confluence_version must be a non-empty string or null")

    root_request = _parse_request_template(payload.get("root_request"), "root_request")
    inventory_request = _parse_request_template(
        payload.get("inventory_request"), "inventory_request"
    )
    pagination = _parse_pagination_profile(payload.get("pagination"))
    _validate_template_scope(root_request, require_page_size=False, name="root_request")
    _validate_template_scope(
        inventory_request,
        require_page_size=True,
        name="inventory_request",
    )
    if pagination.kind == "start_limit":
        _validate_start_limit_template(inventory_request, pagination)
    return RequestProfile(
        deployment=deployment,
        confluence_version=version,
        api_family=api_family,
        auth_scheme=auth_scheme,
        root_request=root_request,
        inventory_request=inventory_request,
        pagination=pagination,
    )


def collect_packet_data(
    *,
    config: ProbeConfig,
    client: ReadOnlyHttpClient,
) -> CollectionResult:
    root_path = render_request_template(
        config.profile.root_request,
        root_page_id=config.root_page_id,
        space_key=config.space_key,
        page_size=config.page_size,
    )
    inventory_path = render_request_template(
        config.profile.inventory_request,
        root_page_id=config.root_page_id,
        space_key=config.space_key,
        page_size=config.page_size,
    )
    root = client.get_json(client.resolve_initial_path(root_path))
    root_identity = _validate_root_identity_and_space(
        payload=root.payload,
        root_page_id=config.root_page_id,
        space_key=config.space_key,
    )
    observations: list[RequestObservation] = [
        RequestObservation(
            sequence=1,
            url=root.url,
            status=root.status,
            content_type=root.content_type,
            link_header=root.link_header,
            pagination_decision="root metadata captured; not paginated",
        )
    ]

    inventory_url = client.resolve_initial_path(inventory_path)
    current_url = inventory_url
    seen_urls: set[str] = set()
    pages: list[HttpResult] = []
    truncated = False
    terminal_observed = False
    mechanism = config.profile.pagination.kind
    next_shapes: list[str] = []
    terminal_condition = "not observed"

    for page_number in range(1, config.max_pages + 1):
        if current_url in seen_urls:
            raise PaginationError("pagination next URL repeated")
        seen_urls.add(current_url)
        page = client.get_json(current_url)
        _validate_inventory_space(page.payload, config.space_key)
        pages.append(page)
        decision = determine_next_page(
            profile=config.profile.pagination,
            response=page,
            client=client,
        )
        if decision.next_url is not None:
            _validate_pagination_scope(
                initial_url=inventory_url,
                next_url=decision.next_url,
                profile=config.profile.pagination,
            )
            next_shape = _describe_next_shape(config.profile.pagination, decision)
            next_shapes.append(next_shape)
        else:
            next_shape = None
        mechanism = decision.mechanism
        terminal_condition = decision.terminal_condition
        if decision.has_next and page_number == config.max_pages:
            truncated = True
            terminal_condition = (
                "not observed; next page existed at max-pages safety cap"
            )
        elif not decision.has_next:
            terminal_observed = True

        observations.append(
            RequestObservation(
                sequence=len(observations) + 1,
                url=page.url,
                status=page.status,
                content_type=page.content_type,
                link_header=page.link_header,
                pagination_decision=(
                    "next page observed; stopped at max-pages safety cap"
                    + (f" ({next_shape})" if next_shape else "")
                    if truncated
                    else (
                        "followed confirmed next page"
                        + (f" ({next_shape})" if next_shape else "")
                        if decision.has_next
                        else decision.terminal_condition
                    )
                ),
            )
        )
        if truncated or not decision.has_next:
            break
        assert decision.next_url is not None
        current_url = decision.next_url

    if not pages:
        raise ResponseError("inventory request returned no response page")
    return CollectionResult(
        root=root,
        root_identity=root_identity,
        descendant_pages=tuple(pages),
        observations=tuple(observations),
        pagination_mechanism=mechanism,
        next_shapes_observed=tuple(dict.fromkeys(next_shapes)),
        terminal_condition=terminal_condition,
        pagination_truncated=truncated,
        terminal_page_observed=terminal_observed,
    )


def determine_next_page(
    *,
    profile: PaginationProfile,
    response: HttpResult,
    client: ReadOnlyHttpClient,
) -> PaginationDecision:
    if profile.kind == "json_next":
        assert profile.next_pointer is not None
        value = json_pointer_get(response.payload, profile.next_pointer, missing=None)
        if value is None or value == "":
            return PaginationDecision(
                mechanism=f"JSON next pointer {profile.next_pointer}",
                next_url=None,
                next_value=None,
                terminal_condition=f"{profile.next_pointer} absent or null",
            )
        if not isinstance(value, str):
            raise PaginationError("configured JSON next pointer did not contain a string")
        return PaginationDecision(
            mechanism=f"JSON next pointer {profile.next_pointer}",
            next_url=client.resolve_next(current_url=response.url, next_value=value),
            next_value=value,
            terminal_condition="next value present",
        )

    if profile.kind == "link_header":
        next_value = extract_link_next(response.link_header)
        if next_value is None:
            return PaginationDecision(
                mechanism="HTTP Link header rel=next",
                next_url=None,
                next_value=None,
                terminal_condition="Link header has no rel=next",
            )
        return PaginationDecision(
            mechanism="HTTP Link header rel=next",
            next_url=client.resolve_next(current_url=response.url, next_value=next_value),
            next_value=next_value,
            terminal_condition="rel=next present",
        )

    if profile.kind == "cursor_value":
        return _determine_cursor_value_next(
            profile=profile,
            response=response,
            client=client,
        )

    if profile.kind == "start_limit":
        return _determine_start_limit_next(profile=profile, response=response, client=client)
    raise PaginationError("unsupported pagination profile kind")


def _determine_cursor_value_next(
    *,
    profile: PaginationProfile,
    response: HttpResult,
    client: ReadOnlyHttpClient,
) -> PaginationDecision:
    assert profile.next_pointer is not None
    assert profile.cursor_query_parameter is not None
    value = json_pointer_get(response.payload, profile.next_pointer, missing=None)
    if value is None or value == "":
        return PaginationDecision(
            mechanism=(
                f"JSON cursor pointer {profile.next_pointer} -> query parameter "
                f"{profile.cursor_query_parameter}"
            ),
            next_url=None,
            next_value=None,
            terminal_condition=f"{profile.next_pointer} absent or null",
        )
    if not isinstance(value, str) or _has_unsafe_text(value):
        raise PaginationError("configured cursor pointer did not contain a safe string")
    parts = urlsplit(response.url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    matches = [
        index
        for index, (key, _) in enumerate(pairs)
        if key == profile.cursor_query_parameter
    ]
    if len(matches) > 1:
        raise PaginationError("cursor query parameter is duplicated")
    if matches:
        pairs[matches[0]] = (profile.cursor_query_parameter, value)
    else:
        pairs.append((profile.cursor_query_parameter, value))
    next_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), "")
    )
    return PaginationDecision(
        mechanism=(
            f"JSON cursor pointer {profile.next_pointer} -> query parameter "
            f"{profile.cursor_query_parameter}"
        ),
        next_url=client.resolve_next(
            current_url=response.url,
            next_value=next_url,
        ),
        next_value=value,
        terminal_condition="cursor value present",
    )


def _validate_pagination_scope(
    *,
    initial_url: str,
    next_url: str,
    profile: PaginationProfile,
) -> None:
    initial = urlsplit(initial_url)
    candidate = urlsplit(next_url)
    if candidate.path != initial.path:
        raise PaginationError("pagination next target changed the inventory path")
    if profile.kind == "start_limit":
        assert profile.start_query_parameter is not None
        mutable = {profile.start_query_parameter}
    else:
        mutable = set(profile.mutable_query_parameters)
    initial_immutable = Counter(
        pair
        for pair in parse_qsl(initial.query, keep_blank_values=True)
        if pair[0] not in mutable
    )
    candidate_immutable = Counter(
        pair
        for pair in parse_qsl(candidate.query, keep_blank_values=True)
        if pair[0] not in mutable
    )
    if candidate_immutable != initial_immutable:
        raise PaginationError("pagination next target changed inventory scope")


def _describe_next_shape(
    profile: PaginationProfile,
    decision: PaginationDecision,
) -> str:
    if profile.kind == "cursor_value":
        return "opaque cursor value applied to a confirmed query parameter"
    if profile.kind == "start_limit":
        return "numeric start value applied to the confirmed start parameter"
    assert decision.next_value is not None
    parts = urlsplit(decision.next_value)
    if parts.scheme or parts.netloc:
        return "absolute URL"
    if decision.next_value.startswith("/"):
        return "root-relative URL"
    if decision.next_value.startswith("?"):
        return "query-relative URL"
    return "path-relative URL"


def extract_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for link_url, parameters in _parse_link_header_entries(link_header):
        rel_value = _link_relation_value(parameters)
        if rel_value is None:
            continue
        if "next" in {part.lower() for part in rel_value.split()}:
            return link_url
    return None


def _parse_link_header_entries(value: str) -> tuple[tuple[str, str], ...]:
    raw_entries: list[str] = []
    start = 0
    in_angle = False
    quote_character: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote_character is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote_character:
                quote_character = None
            continue
        if character in {'"', "'"} and not in_angle:
            quote_character = character
        elif character == "<":
            in_angle = True
        elif character == ">":
            in_angle = False
        elif character == "," and not in_angle:
            raw_entries.append(value[start:index])
            start = index + 1
    raw_entries.append(value[start:])

    parsed: list[tuple[str, str]] = []
    for raw_entry in raw_entries:
        match = re.fullmatch(r"\s*<([^>]*)>\s*(.*)\s*", raw_entry)
        if match:
            parsed.append((match.group(1), match.group(2)))
    return tuple(parsed)


def _link_relation_value(parameters: str) -> str | None:
    for name, value in _parse_link_parameters(parameters):
        if name.casefold() == "rel":
            return value
    return None


def _parse_link_parameters(value: str) -> tuple[tuple[str, str], ...]:
    raw_parameters: list[str] = []
    start = 0
    quote_character: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote_character is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote_character:
                quote_character = None
            continue
        if character in {'"', "'"}:
            quote_character = character
        elif character == ";":
            raw_parameters.append(value[start:index])
            start = index + 1
    if quote_character is not None or escaped:
        return ()
    raw_parameters.append(value[start:])

    parsed: list[tuple[str, str]] = []
    for raw_parameter in raw_parameters:
        name, separator, raw_value = raw_parameter.strip().partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", name):
            continue
        raw_value = raw_value.strip()
        if raw_value[:1] in {'"', "'"}:
            quote_character = raw_value[0]
            if len(raw_value) < 2 or raw_value[-1] != quote_character:
                continue
            inner = raw_value[1:-1]
            decoded: list[str] = []
            escaped = False
            for character in inner:
                if escaped:
                    decoded.append(character)
                    escaped = False
                elif character == "\\":
                    escaped = True
                else:
                    decoded.append(character)
            if escaped:
                continue
            parameter_value = "".join(decoded)
        else:
            if not raw_value or any(character.isspace() for character in raw_value):
                continue
            parameter_value = raw_value
        parsed.append((name, parameter_value))
    return tuple(parsed)


def render_request_template(
    template: RequestTemplate,
    *,
    root_page_id: str,
    space_key: str,
    page_size: int,
) -> str:
    values = {
        "root_page_id": root_page_id,
        "space_key": space_key,
        "page_size": str(page_size),
    }
    path = _format_template_component(template.path_template, values, is_path=True)
    rendered_query = [
        (
            _format_template_component(key, values, is_path=False),
            _format_template_component(value, values, is_path=False),
        )
        for key, value in template.query
    ]
    query = urlencode(rendered_query, doseq=True)
    return f"{path}?{query}" if query else path


def render_packet(
    *,
    config: ProbeConfig,
    base_url: str,
    token: str,
    known_identities: Sequence[str],
    collection: CollectionResult,
) -> dict[str, bytes]:
    sanitizer = Sanitizer(
        base_url=base_url,
        root_page_id=collection.root_identity,
        space_key=config.space_key,
        safe_path_segments=_profile_safe_path_segments(config.profile),
        safe_query_values=_profile_safe_query_values(config.profile),
        cursor_keys=_profile_cursor_keys(config.profile),
    )
    sanitizer.prime(collection.root.payload)
    for page in collection.descendant_pages:
        sanitizer.prime(page.payload)

    sanitized_root = sanitizer.sanitize(collection.root.payload)
    sanitized_pages = [sanitizer.sanitize(page.payload) for page in collection.descendant_pages]
    _validate_shape(collection.root.payload, sanitized_root)
    sensitive_scalars = _collect_sensitive_scalar_values(
        [
            collection.root.payload,
            *(page.payload for page in collection.descendant_pages),
        ]
    )
    _validate_sensitive_replacements(
        collection.root.payload,
        sanitized_root,
        forbidden_scalars=sensitive_scalars,
    )
    for raw_page, sanitized_page in zip(collection.descendant_pages, sanitized_pages):
        _validate_shape(raw_page.payload, sanitized_page)
        _validate_sensitive_replacements(
            raw_page.payload,
            sanitized_page,
            forbidden_scalars=sensitive_scalars,
        )
    if not _contains_scalar(sanitized_root, sanitizer.sanitized_root_id()):
        raise PacketValidationError("sanitized root response lost the requested root identity")

    fields_observed, fields_unavailable = observe_metadata_fields(
        [collection.root.payload, *(page.payload for page in collection.descendant_pages)]
    )
    profile_text = render_api_profile(
        config=config,
        collection=collection,
        sanitizer=sanitizer,
        fields_observed=fields_observed,
        fields_unavailable=fields_unavailable,
    )
    trace_text = render_request_trace(collection.observations, sanitizer)
    report_text = render_sanitization_report(collection)

    files: dict[str, bytes] = {
        "confluence_api_profile.md": profile_text.encode("utf-8"),
        "confluence_request_trace.md": trace_text.encode("utf-8"),
        "root_page_response.sanitized.json": render_json(sanitized_root),
        "descendants_page_1.sanitized.json": render_json(sanitized_pages[0]),
        "sanitization_report.md": report_text.encode("utf-8"),
    }
    if len(sanitized_pages) >= 2:
        files["descendants_page_2.sanitized.json"] = render_json(sanitized_pages[1])
    if len(sanitized_pages) >= 3 and collection.terminal_page_observed:
        files["descendants_last_page.sanitized.json"] = render_json(sanitized_pages[-1])

    validate_rendered_packet(
        files=files,
        base_url=base_url,
        token=token,
        known_identities=known_identities,
    )
    return files


def render_json(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PacketValidationError("sanitized JSON could not be serialized strictly") from exc
    return (text + "\n").encode("utf-8")


def _profile_safe_path_segments(profile: RequestProfile) -> tuple[str, ...]:
    segments: list[str] = []
    for template in (profile.root_request, profile.inventory_request):
        for segment in template.path_template.split("/"):
            if segment and "{" not in segment and "}" not in segment:
                segments.append(_url_decode_component(segment))
    return tuple(dict.fromkeys(segments))


def _profile_safe_query_values(
    profile: RequestProfile,
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for template in (profile.root_request, profile.inventory_request):
        for key, value in template.query:
            if (
                _normalize_key(key) in {"expand", "fields"}
                and "{" not in key
                and "}" not in key
                and "{" not in value
                and "}" not in value
            ):
                values.append((key, value))
    return tuple(dict.fromkeys(values))


def _profile_cursor_keys(profile: RequestProfile) -> tuple[str, ...]:
    keys = list(profile.pagination.mutable_query_parameters)
    if profile.pagination.cursor_query_parameter:
        keys.append(profile.pagination.cursor_query_parameter)
    if profile.pagination.kind == "cursor_value" and profile.pagination.next_pointer:
        raw_token = profile.pagination.next_pointer.rsplit("/", 1)[-1]
        keys.append(raw_token.replace("~1", "/").replace("~0", "~"))
    return tuple(dict.fromkeys(keys))


def _strict_json_loads(value: str) -> object:
    def reject_constant(constant: str) -> object:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    return json.loads(value, parse_constant=reject_constant)


def render_api_profile(
    *,
    config: ProbeConfig,
    collection: CollectionResult,
    sanitizer: Sanitizer,
    fields_observed: Sequence[str],
    fields_unavailable: Sequence[str],
) -> str:
    root_shape = _path_query_only(sanitizer.sanitize_url(collection.root.url))
    inventory_shape = _path_query_only(
        sanitizer.sanitize_url(collection.descendant_pages[0].url)
    )
    version = config.profile.confluence_version or "not confirmed"
    attachment_behavior = (
        "observed in response shape"
        if "attachment count" in fields_observed
        else "unavailable without extra requests"
    )
    labels_behavior = (
        "observed in response shape"
        if "labels" in fields_observed
        else "unavailable without extra requests"
    )
    mutable_keys = (
        (config.profile.pagination.start_query_parameter,)
        if config.profile.pagination.kind == "start_limit"
        else config.profile.pagination.mutable_query_parameters
    )
    lines = [
        "# Sanitized Confluence API Profile",
        "",
        f"- Deployment type: `{config.profile.deployment}`",
        f"- Version: `{version}`",
        f"- REST API family: `{config.profile.api_family}`",
        f"- Authentication scheme: `{config.profile.auth_scheme}`",
        "- Root request method: `GET`",
        f"- Root request path/query shape: `{root_shape}`",
        "- Inventory request method: `GET`",
        f"- Inventory request path/query shape: `{inventory_shape}`",
        f"- Requested page size: `{config.page_size}`",
        f"- Descendant response pages observed: `{len(collection.descendant_pages)}`",
        f"- Pagination mechanism: `{collection.pagination_mechanism}`",
        "- Mutable pagination query keys: `"
        + (", ".join(key for key in mutable_keys if key) or "none")
        + "`",
        "- Next-page value/URL shapes observed: `"
        + (
            ", ".join(collection.next_shapes_observed)
            if collection.next_shapes_observed
            else "none"
        )
        + "`",
        f"- Terminal condition: `{collection.terminal_condition}`",
        f"- Pagination truncated: `{str(collection.pagination_truncated).lower()}`",
        f"- Attachment-count behavior: {attachment_behavior}",
        f"- Labels behavior: {labels_behavior}",
        "",
        "## Metadata fields observed",
        "",
    ]
    lines.extend(f"- {field}" for field in fields_observed)
    lines.extend(["", "## Metadata fields unavailable", ""])
    lines.extend(f"- {field}" for field in fields_unavailable)
    return "\n".join(lines) + "\n"


def render_request_trace(
    observations: Sequence[RequestObservation],
    sanitizer: Sanitizer,
) -> str:
    lines = ["# Sanitized Confluence Request Trace", ""]
    for observation in observations:
        lines.extend(
            [
                f"## Request {observation.sequence}",
                "",
                "- Method: `GET`",
                f"- Path/query: `{_path_query_only(sanitizer.sanitize_url(observation.url))}`",
                f"- HTTP status: `{observation.status}`",
                f"- Content-Type: `{observation.content_type}`",
                "- Link header shape: "
                f"`{sanitizer.sanitize_link_header(observation.link_header) or 'not present'}`",
                f"- Pagination decision: {observation.pagination_decision}",
                "",
            ]
        )
    return "\n".join(lines)


def render_sanitization_report(collection: CollectionResult) -> str:
    return "\n".join(
        [
            "# Sanitization Report",
            "",
            "- Raw HTTP responses were held in memory only and were not saved.",
            "- Credential, authorization, cookie, and session fields were not written.",
            "- Real hostnames were replaced with `<CONFLUENCE_HOST>`.",
            "- Page titles, people, labels, account identifiers, and unknown text were sanitized.",
            "- Page body value leaves were replaced while JSON object/list structure was retained.",
            "- Page IDs use stable synthetic mappings and preserve JSON integer/string types.",
            "- Pagination field names, nesting, and relative/absolute URL shape were preserved.",
            f"- Pagination truncated: `{str(collection.pagination_truncated).lower()}`.",
            "- All recorded request methods are `GET`.",
            "",
        ]
    )


def observe_metadata_fields(payloads: Iterable[object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    keys: set[str] = set()
    for payload in payloads:
        _collect_normalized_keys(payload, keys)
    definitions = {
        "page ID": {"id", "pageid", "page_id"},
        "title": {"title"},
        "space / space key": {"space", "spacekey", "space_key"},
        "parent": {"parent", "parentid", "parent_id", "parentpageid"},
        "ancestors": {"ancestors", "ancestorids", "ancestor_page_ids"},
        "version": {"version", "versionnumber"},
        "updated timestamp": {"when", "updated", "updatedat", "lastmodified"},
        "labels": {"label", "labels"},
        "attachment count": {"attachmentcount", "attachment_count"},
    }
    observed = tuple(
        name for name, aliases in definitions.items() if keys.intersection(aliases)
    )
    unavailable = tuple(name for name in definitions if name not in observed)
    return observed, unavailable


def validate_rendered_packet(
    *,
    files: Mapping[str, bytes],
    base_url: str,
    token: str,
    known_identities: Sequence[str],
) -> None:
    expected = set(ALWAYS_PACKET_FILES)
    if "descendants_page_2.sanitized.json" in files:
        expected.add("descendants_page_2.sanitized.json")
    if "descendants_last_page.sanitized.json" in files:
        expected.add("descendants_last_page.sanitized.json")
        if "descendants_page_2.sanitized.json" not in files:
            raise PacketValidationError("last descendant page requires page 2")
    if set(files) != expected:
        raise PacketValidationError("rendered packet file set is invalid")

    real_hostname = urlsplit(_normalize_base_url(base_url)).hostname or ""
    for name, content in files.items():
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PacketValidationError(f"packet file {name} is not UTF-8") from exc
        scan_text = text.replace("<CONFLUENCE_HOST>", "")
        categories: list[str] = []
        for label, forbidden in (
            ("base URL", base_url),
            ("hostname", real_hostname),
            ("credential", token),
        ):
            if forbidden and forbidden.casefold() in scan_text.casefold():
                categories.append(label)
        for encoded_hostname in _encoded_secret_variants(real_hostname):
            if encoded_hostname.casefold() in scan_text.casefold():
                categories.append("encoded hostname")
        for encoded_token in _encoded_secret_variants(token):
            if encoded_token.casefold() in scan_text.casefold():
                categories.append("encoded credential")
        token_base64 = base64.b64encode(token.encode("utf-8")).decode("ascii")
        if token_base64 and token_base64 in text:
            categories.append("base64 credential")
        for identity in known_identities:
            if identity and identity.casefold() in scan_text.casefold():
                categories.append("known identity")
            for encoded_identity in _encoded_secret_variants(identity):
                if encoded_identity.casefold() in scan_text.casefold():
                    categories.append("encoded known identity")
            basic_material = base64.b64encode(
                f"{identity}:{token}".encode("utf-8")
            ).decode("ascii")
            if basic_material and basic_material in text:
                categories.append("basic credential material")
        if HEADER_LEAK_RE.search(text):
            categories.append("sensitive header")
        if BEARER_MATERIAL_RE.search(text):
            categories.append("bearer credential material")
        if categories:
            unique = ", ".join(sorted(set(categories)))
            raise PacketValidationError(
                f"packet validation detected {unique} in {name}; values withheld"
            )
        if name.endswith(".json"):
            try:
                _strict_json_loads(text)
            except ValueError as exc:
                raise PacketValidationError(f"packet JSON file {name} does not parse") from exc
            if not content.endswith(b"\n") or content.endswith(b"\n\n"):
                raise PacketValidationError(
                    f"packet JSON file {name} must have one final newline"
                )


def _collect_sensitive_scalar_values(
    payloads: Iterable[object],
) -> frozenset[tuple[type[object], object]]:
    collected: set[tuple[type[object], object]] = set()
    for payload in payloads:
        _collect_sensitive_scalar_values_from_value(
            payload,
            key=None,
            path=(),
            target=collected,
        )
    return frozenset(collected)


def _collect_sensitive_scalar_values_from_value(
    value: object,
    *,
    key: str | None,
    path: tuple[str, ...],
    target: set[tuple[type[object], object]],
) -> None:
    normalized_key = _normalize_key(key)
    next_path = (*path, normalized_key)
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _collect_sensitive_scalar_values_from_value(
                child,
                key=str(child_key),
                path=next_path,
                target=target,
            )
        return
    if isinstance(value, list):
        for child in value:
            _collect_sensitive_scalar_values_from_value(
                child,
                key=key,
                path=path,
                target=target,
            )
        return
    if _scalar_requires_replacement(value, normalized_key, path):
        target.add((type(value), value))


def _validate_sensitive_replacements(
    raw: object,
    sanitized: object,
    *,
    forbidden_scalars: frozenset[tuple[type[object], object]],
    key: str | None = None,
    path: tuple[str, ...] = (),
) -> None:
    normalized_key = _normalize_key(key)
    next_path = (*path, normalized_key)
    if isinstance(raw, Mapping):
        assert isinstance(sanitized, Mapping)
        for child_key, child in raw.items():
            _validate_sensitive_replacements(
                child,
                sanitized[child_key],
                forbidden_scalars=forbidden_scalars,
                key=str(child_key),
                path=next_path,
            )
        return
    if isinstance(raw, list):
        assert isinstance(sanitized, list)
        for raw_child, sanitized_child in zip(raw, sanitized):
            _validate_sensitive_replacements(
                raw_child,
                sanitized_child,
                forbidden_scalars=forbidden_scalars,
                key=key,
                path=path,
            )
        return
    if not _scalar_requires_replacement(raw, normalized_key, path):
        return
    sanitized_key = (type(sanitized), sanitized)
    if sanitized == raw or sanitized_key in forbidden_scalars:
        raise PacketValidationError(
            "sanitization retained or collided with a sensitive scalar value"
        )


def _scalar_requires_replacement(
    value: object,
    normalized_key: str,
    path: tuple[str, ...],
) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        if value in {"<SANITIZED_BODY>", "<CONFLUENCE_HOST>"}:
            return False
        if Sanitizer._is_url_context(normalized_key, value):
            return False
        if _is_safe_technical_value(normalized_key, value):
            return False
        return True
    if isinstance(value, (int, float)):
        return (
            Sanitizer._is_identity_context(normalized_key, path)
            or Sanitizer._is_page_id_context(normalized_key, path)
            or normalized_key not in SAFE_NUMBER_KEYS
        )
    return True


def write_packet(*, output_dir: Path, files: Mapping[str, bytes]) -> None:
    try:
        output_exists = output_dir.exists()
        if output_exists:
            if output_dir.is_symlink() or not output_dir.is_dir():
                raise OutputError("output path must be a real directory")
            if any(output_dir.iterdir()):
                raise OutputError("output directory must be empty")
        else:
            output_dir.mkdir(parents=False, exist_ok=False)
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError("output directory could not be prepared") from exc

    for name, content in files.items():
        if Path(name).name != name:
            raise OutputError("packet filename is invalid")
        target = output_dir / name
        _write_new_file(target, content)
    try:
        actual_names = {path.name for path in output_dir.iterdir()}
        if actual_names != set(files):
            raise OutputError("output directory contains unexpected entries")
        for name in files:
            path = output_dir / name
            if path.is_symlink() or not path.is_file():
                raise OutputError("packet output contains a non-regular file")
            try:
                on_disk = path.read_bytes()
            except OSError as exc:
                raise OutputError("packet output could not be verified") from exc
            if on_disk != files[name]:
                raise OutputError("packet output changed during publication")
            if name.endswith(".json"):
                try:
                    _strict_json_loads(on_disk.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise OutputError("packet JSON changed during publication") from exc
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError("packet output could not be verified") from exc


def json_pointer_get(value: object, pointer: str, *, missing: object) -> object:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise InputError("JSON pointer must be empty or start with '/'")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return missing
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                return missing
            current = current[index]
        else:
            return missing
    return current


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        profile = load_request_profile(args.request_profile)
        if args.validate_profile_only:
            print("OK: request profile is valid; no network request was made.")
            return EXIT_OK
        if args.verify_packet_only:
            _verify_existing_packet(args=args, profile=profile)
            print("OK: existing packet passed the sanitized leak scan; no network request was made.")
            return EXIT_OK
        config = _build_config(args=args, profile=profile)
        _preflight_output_dir(config.output_dir)
        base_url = _read_base_url()
        token = _read_pat()
        username: str | None = None
        if profile.auth_scheme == "basic_username_pat":
            username = _read_username()
        authorization_value = _build_authorization(
            auth_scheme=profile.auth_scheme,
            token=token,
            username=username,
        )
        client = ReadOnlyHttpClient(
            base_url=base_url,
            authorization_value=authorization_value,
            timeout_seconds=config.timeout_seconds,
        )
        collection = collect_packet_data(config=config, client=client)
        known_identities = _known_scan_identities(
            username,
            prompt=args.prompt_scan_identities,
        )
        files = render_packet(
            config=config,
            base_url=base_url,
            token=token,
            known_identities=known_identities,
            collection=collection,
        )
        write_packet(output_dir=config.output_dir, files=files)
        print(
            "SUCCESS: sanitized packet created; "
            f"descendant_pages={len(collection.descendant_pages)}; "
            f"pagination_truncated={str(collection.pagination_truncated).lower()}."
        )
        return EXIT_OK
    except ProbeError as exc:
        print(f"ERROR[{exc.exit_code}]: {exc.safe_message}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(
            f"ERROR[{EXIT_UNEXPECTED}]: unexpected {type(exc).__name__}; details withheld",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED


def _build_config(*, args: argparse.Namespace, profile: RequestProfile) -> ProbeConfig:
    for name in ("space_key", "root_page_id"):
        value = getattr(args, name)
        if not isinstance(value, str) or not value:
            raise InputError(f"--{name.replace('_', '-')} is required")
        if _has_unsafe_text(value) or len(value) > 1024:
            raise InputError(f"--{name.replace('_', '-')} contains unsafe text")
    if args.output_dir is None:
        raise InputError("--output-dir is required")
    if isinstance(args.page_size, bool) or not 1 <= args.page_size <= 100:
        raise InputError("--page-size must be in the range [1, 100]")
    if isinstance(args.max_pages, bool) or not 1 <= args.max_pages <= 20:
        raise InputError("--max-pages must be in the range [1, 20]")
    if (
        not math.isfinite(args.timeout_seconds)
        or args.timeout_seconds <= 0
        or args.timeout_seconds > 300
    ):
        raise InputError("--timeout-seconds must be in the range (0, 300]")
    return ProbeConfig(
        profile=profile,
        space_key=args.space_key,
        root_page_id=args.root_page_id,
        page_size=args.page_size,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout_seconds,
        output_dir=args.output_dir.expanduser().resolve(),
    )


def _verify_existing_packet(
    *,
    args: argparse.Namespace,
    profile: RequestProfile,
) -> None:
    if args.output_dir is None:
        raise InputError("--output-dir is required with --verify-packet-only")
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise OutputError("packet path must be a real directory")
    files: dict[str, bytes] = {}
    try:
        entries = tuple(output_dir.iterdir())
        for path in entries:
            if path.is_symlink() or not path.is_file():
                raise OutputError("packet contains a non-regular entry")
            files[path.name] = path.read_bytes()
    except OSError as exc:
        raise OutputError("existing packet could not be read") from exc
    base_url = _read_base_url()
    token = _read_pat()
    username: str | None = None
    if profile.auth_scheme == "basic_username_pat":
        username = _read_username()
    validate_rendered_packet(
        files=files,
        base_url=base_url,
        token=token,
        known_identities=_known_scan_identities(
            username,
            prompt=args.prompt_scan_identities,
        ),
    )


def _parse_request_template(value: object, field_name: str) -> RequestTemplate:
    if not isinstance(value, dict):
        raise InputError(f"{field_name} must be an object")
    path_template = value.get("path_template")
    if not isinstance(path_template, str) or not path_template.startswith("/"):
        raise InputError(f"{field_name}.path_template must start with '/'")
    if _contains_unresolved_marker(path_template):
        raise InputError(f"{field_name}.path_template is still a placeholder")
    parts = urlsplit(path_template)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise InputError(f"{field_name}.path_template must contain a relative path only")
    if _has_unsafe_text(path_template) or any(
        character.isspace() for character in path_template
    ):
        raise InputError(f"{field_name}.path_template contains unsafe text")
    if _is_forbidden_request_resource(path_template):
        raise InputError(f"{field_name} requests a prohibited resource")
    query_value = value.get("query", [])
    if not isinstance(query_value, list):
        raise InputError(f"{field_name}.query must be an ordered list")
    query: list[tuple[str, str]] = []
    for entry in query_value:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not all(isinstance(part, str) for part in entry)
        ):
            raise InputError(f"{field_name}.query entries must be [name, value]")
        if any(_contains_unresolved_marker(part) for part in entry):
            raise InputError(f"{field_name}.query is still a placeholder")
        if not entry[0] or any(_has_unsafe_text(part) for part in entry):
            raise InputError(f"{field_name}.query contains unsafe text")
        query.append((entry[0], entry[1]))
    _validate_placeholders(path_template, field_name)
    for key, query_item in query:
        _validate_placeholders(key, field_name)
        _validate_placeholders(query_item, field_name)
        if _is_forbidden_request_resource(key) or _is_forbidden_request_resource(
            query_item
        ):
            raise InputError(f"{field_name} requests a prohibited resource")
    return RequestTemplate(path_template=path_template, query=tuple(query))


def _parse_pagination_profile(value: object) -> PaginationProfile:
    if not isinstance(value, dict):
        raise InputError("pagination must be an object")
    kind = _required_choice(
        value,
        "kind",
        {"json_next", "link_header", "cursor_value", "start_limit"},
    )
    if kind == "json_next":
        pointer = _required_non_placeholder_string(value, "next_pointer")
        json_pointer_get({}, pointer, missing=None)
        return PaginationProfile(
            kind=kind,
            next_pointer=pointer,
            mutable_query_parameters=_parse_mutable_query_parameters(value),
        )
    if kind == "link_header":
        return PaginationProfile(
            kind=kind,
            mutable_query_parameters=_parse_mutable_query_parameters(value),
        )
    if kind == "cursor_value":
        pointer = _required_non_placeholder_string(value, "next_pointer")
        json_pointer_get({}, pointer, missing=None)
        cursor_parameter = _required_non_placeholder_string(
            value,
            "cursor_query_parameter",
        )
        _validate_mutable_query_parameter_name(cursor_parameter)
        return PaginationProfile(
            kind=kind,
            next_pointer=pointer,
            cursor_query_parameter=cursor_parameter,
            mutable_query_parameters=(cursor_parameter,),
        )

    required_names = (
        "start_query_parameter",
        "limit_query_parameter",
        "response_start_pointer",
        "response_limit_pointer",
        "response_size_pointer",
        "response_total_pointer",
        "terminal_rule",
    )
    parsed = {name: _required_non_placeholder_string(value, name) for name in required_names}
    if parsed["terminal_rule"] != "start_plus_size_gte_total":
        raise InputError("start_limit terminal_rule must be start_plus_size_gte_total")
    for name in (
        "response_start_pointer",
        "response_limit_pointer",
        "response_size_pointer",
        "response_total_pointer",
    ):
        json_pointer_get({}, parsed[name], missing=None)
    return PaginationProfile(kind=kind, **parsed)


def _parse_mutable_query_parameters(
    value: Mapping[str, object],
) -> tuple[str, ...]:
    raw_parameters = value.get("mutable_query_parameters")
    if not isinstance(raw_parameters, list) or not all(
        isinstance(parameter, str) and parameter
        for parameter in raw_parameters
    ):
        raise InputError("mutable_query_parameters must be a list of query names")
    parameters = tuple(raw_parameters)
    if len(set(parameters)) != len(parameters):
        raise InputError("mutable_query_parameters must not contain duplicates")
    for parameter in parameters:
        _validate_mutable_query_parameter_name(parameter)
    return parameters


def _validate_mutable_query_parameter_name(parameter: str) -> None:
    if _contains_unresolved_marker(parameter) or _has_unsafe_text(parameter):
        raise InputError("pagination query parameter contains an invalid name")
    normalized = _normalize_key(parameter)
    if (
        "space" in normalized
        or "root" in normalized
        or normalized in PAGE_ID_KEYS
        or normalized
        in {
            "cql",
            "query",
            "filter",
            "expand",
            "fields",
            "parent",
            "ancestor",
            "type",
            "status",
            "limit",
        }
    ):
        raise InputError("pagination query parameter must not change inventory scope")


def _validate_template_scope(
    template: RequestTemplate,
    *,
    require_page_size: bool,
    name: str,
) -> None:
    combined = "\n".join(
        [template.path_template, *(part for pair in template.query for part in pair)]
    )
    if "{root_page_id}" not in combined:
        raise InputError(f"{name} must be scoped by root_page_id")
    if require_page_size and "{page_size}" not in combined:
        raise InputError(f"{name} must include page_size")


def _validate_start_limit_template(
    template: RequestTemplate,
    pagination: PaginationProfile,
) -> None:
    assert pagination.start_query_parameter is not None
    assert pagination.limit_query_parameter is not None
    start_values = [
        value
        for key, value in template.query
        if key == pagination.start_query_parameter
    ]
    limit_values = [
        value
        for key, value in template.query
        if key == pagination.limit_query_parameter
    ]
    if len(start_values) != 1 or len(limit_values) != 1:
        raise InputError(
            "start_limit inventory query must contain one start and one limit parameter"
        )
    if not start_values[0].isdigit():
        raise InputError("start_limit initial start value must be a non-negative integer")
    if "{page_size}" not in limit_values[0]:
        raise InputError("start_limit limit parameter must use {page_size}")


def _validate_placeholders(value: str, field_name: str) -> None:
    formatter = string.Formatter()
    try:
        fields = {
            field_name_value
            for _, field_name_value, _, _ in formatter.parse(value)
            if field_name_value is not None
        }
    except ValueError as exc:
        raise InputError(f"{field_name} contains invalid template braces") from exc
    if not fields.issubset(ALLOWED_PLACEHOLDERS):
        raise InputError(f"{field_name} contains an unsupported placeholder")


def _format_template_component(
    value: str,
    replacements: Mapping[str, str],
    *,
    is_path: bool,
) -> str:
    formatted_values = {
        key: quote(raw_value, safe="") if is_path else raw_value
        for key, raw_value in replacements.items()
    }
    try:
        return value.format_map(formatted_values)
    except (KeyError, ValueError) as exc:
        raise InputError("request template could not be rendered") from exc


def _determine_start_limit_next(
    *,
    profile: PaginationProfile,
    response: HttpResult,
    client: ReadOnlyHttpClient,
) -> PaginationDecision:
    pointers = (
        profile.response_start_pointer,
        profile.response_limit_pointer,
        profile.response_size_pointer,
        profile.response_total_pointer,
    )
    assert all(pointer is not None for pointer in pointers)
    values = [json_pointer_get(response.payload, pointer or "", missing=None) for pointer in pointers]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise PaginationError("start_limit response pointers must resolve to integers")
    start, limit, size, total = values
    assert isinstance(start, int) and isinstance(limit, int)
    assert isinstance(size, int) and isinstance(total, int)
    if start < 0 or limit <= 0 or size < 0 or total < 0 or start > total:
        raise PaginationError("start_limit response values are invalid")
    assert profile.start_query_parameter is not None
    assert profile.limit_query_parameter is not None
    pairs = parse_qsl(urlsplit(response.url).query, keep_blank_values=True)
    request_start = _single_non_negative_query_integer(
        pairs,
        profile.start_query_parameter,
    )
    request_limit = _single_non_negative_query_integer(
        pairs,
        profile.limit_query_parameter,
    )
    if request_limit <= 0:
        raise PaginationError("confirmed limit query parameter must be positive")
    if start != request_start or limit != request_limit:
        raise PaginationError("start_limit response does not match the request window")
    if size > limit:
        raise PaginationError("start_limit response size exceeds its limit")
    if start + size >= total:
        return PaginationDecision(
            mechanism="confirmed start/limit",
            next_url=None,
            next_value=None,
            terminal_condition="start + size >= total",
        )
    next_start = start + size
    if next_start <= start:
        raise PaginationError("start_limit response did not advance pagination")
    updated_pairs: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == profile.start_query_parameter:
            updated_pairs.append((key, str(next_start)))
        else:
            updated_pairs.append((key, value))
    parts = urlsplit(response.url)
    next_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(updated_pairs), "")
    )
    next_url = client.resolve_next(current_url=response.url, next_value=next_url)
    return PaginationDecision(
        mechanism="confirmed start/limit",
        next_url=next_url,
        next_value=str(next_start),
        terminal_condition="start + size < total",
    )


def _single_non_negative_query_integer(
    pairs: Sequence[tuple[str, str]],
    parameter: str,
) -> int:
    values = [value for key, value in pairs if key == parameter]
    if len(values) != 1 or not values[0].isdigit():
        raise PaginationError(
            "confirmed pagination query parameter must occur once as an integer"
        )
    return int(values[0])


def _validate_root_identity_and_space(
    *,
    payload: object,
    root_page_id: str,
    space_key: str,
) -> object:
    candidates: list[tuple[object, tuple[str, ...]]] = []
    _collect_root_candidates(payload, candidates=candidates, path=())
    matching_candidates = [
        candidate
        for candidate in candidates
        if str(candidate[0]) == root_page_id
    ]
    if not matching_candidates:
        raise ResponseError("root response does not contain the requested page identity")
    observed_spaces = tuple(
        observed_space
        for _, candidate_spaces in matching_candidates
        for observed_space in candidate_spaces
    )
    if any(observed_space != space_key for observed_space in observed_spaces):
        raise ResponseError("root response belongs to a different space")
    return matching_candidates[0][0]


def _collect_root_candidates(
    value: object,
    *,
    candidates: list[tuple[object, tuple[str, ...]]],
    path: tuple[str, ...],
) -> None:
    if isinstance(value, Mapping):
        direct_ids: list[object] = []
        if not any(token in IDENTITY_CONTEXT_KEYS for token in path):
            for key, child in value.items():
                if (
                    _normalize_key(str(key)) in PAGE_ID_KEYS
                    and isinstance(child, (str, int))
                    and not isinstance(child, bool)
                ):
                    direct_ids.append(child)
        direct_spaces = _direct_space_keys(value)
        candidates.extend((page_id, direct_spaces) for page_id in direct_ids)
        for key, child in value.items():
            normalized = _normalize_key(str(key))
            next_path = (*path, normalized)
            _collect_root_candidates(
                child,
                candidates=candidates,
                path=next_path,
            )
    elif isinstance(value, list):
        for child in value:
            _collect_root_candidates(
                child,
                candidates=candidates,
                path=path,
            )


def _direct_space_keys(value: Mapping[object, object]) -> tuple[str, ...]:
    space_keys: list[str] = []
    for key, child in value.items():
        normalized = _normalize_key(str(key))
        if normalized in {"spacekey", "space_key"} and isinstance(child, str):
            space_keys.append(child)
        elif normalized == "space" and isinstance(child, Mapping):
            for space_key, space_value in child.items():
                if (
                    _normalize_key(str(space_key))
                    in {"key", "spacekey", "space_key"}
                    and isinstance(space_value, str)
                ):
                    space_keys.append(space_value)
    return tuple(dict.fromkeys(space_keys))


def _validate_inventory_space(payload: object, expected_space_key: str) -> None:
    observed: list[str] = []
    _collect_explicit_space_keys(payload, observed)
    if any(space_key != expected_space_key for space_key in observed):
        raise ResponseError("inventory response contains a different space")


def _collect_explicit_space_keys(value: object, target: list[str]) -> None:
    if isinstance(value, Mapping):
        target.extend(_direct_space_keys(value))
        for child in value.values():
            _collect_explicit_space_keys(child, target)
    elif isinstance(value, list):
        for child in value:
            _collect_explicit_space_keys(child, target)


def _validate_shape(raw: object, sanitized: object) -> None:
    if isinstance(raw, Mapping):
        if not isinstance(sanitized, Mapping) or list(raw.keys()) != list(sanitized.keys()):
            raise PacketValidationError("sanitization changed JSON object structure")
        for key in raw:
            _validate_shape(raw[key], sanitized[key])
        return
    if isinstance(raw, list):
        if not isinstance(sanitized, list) or len(raw) != len(sanitized):
            raise PacketValidationError("sanitization changed JSON list structure")
        for raw_child, sanitized_child in zip(raw, sanitized):
            _validate_shape(raw_child, sanitized_child)
        return
    if raw is None:
        if sanitized is not None:
            raise PacketValidationError("sanitization changed null type")
        return
    if type(raw) is not type(sanitized):
        raise PacketValidationError("sanitization changed a JSON scalar type")


def _contains_scalar(value: object, expected: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_scalar(child, expected) for child in value.values())
    if isinstance(value, list):
        return any(_contains_scalar(child, expected) for child in value)
    return type(value) is type(expected) and value == expected


def _collect_normalized_keys(value: object, target: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = _normalize_key(str(key))
            if normalized_key in METADATA_HINT_CONTEXT_KEYS:
                continue
            target.add(normalized_key)
            _collect_normalized_keys(child, target)
    elif isinstance(value, list):
        for child in value:
            _collect_normalized_keys(child, target)


def _write_new_file(target: Path, content: bytes) -> None:
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
            temp_file.write(content)
        os.link(temp_path, target)
        if not target.samefile(temp_path):
            raise OutputError("packet target changed during publication")
    except Exception as exc:
        if isinstance(exc, OutputError):
            raise
        if isinstance(exc, OSError):
            raise OutputError("packet file could not be published without overwrite") from exc
        raise
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _preflight_output_dir(output_dir: Path) -> None:
    try:
        if output_dir.exists():
            if output_dir.is_symlink() or not output_dir.is_dir():
                raise OutputError("output path must be a real directory")
            if any(output_dir.iterdir()):
                raise OutputError("output directory must be empty")
        elif not output_dir.parent.is_dir():
            raise OutputError("output parent directory must already exist")
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError("output directory could not be inspected") from exc


def _read_base_url() -> str:
    value = os.environ.get("CONFLUENCE_BASE_URL")
    if value is None:
        if not sys.stdin.isatty():
            raise CredentialError("CONFLUENCE_BASE_URL is required in non-interactive mode")
        value = input("Confluence base URL (not saved): ").strip()
    return _normalize_base_url(value)


def _read_pat() -> str:
    value = os.environ.get("CONFLUENCE_PAT")
    if value is not None:
        if not value:
            raise CredentialError("CONFLUENCE_PAT is empty")
        return _validate_secret_input(value, "CONFLUENCE_PAT")
    if not sys.stdin.isatty():
        raise CredentialError("CONFLUENCE_PAT is required in non-interactive mode")
    value = getpass.getpass("Confluence PAT (hidden, not saved): ")
    if not value:
        raise CredentialError("Confluence PAT must not be empty")
    return _validate_secret_input(value, "Confluence PAT")


def _read_username() -> str:
    value = os.environ.get("CONFLUENCE_USERNAME")
    if value:
        return _validate_username(value)
    if not sys.stdin.isatty():
        raise CredentialError("CONFLUENCE_USERNAME is required for basic auth")
    value = getpass.getpass("Confluence username/email (hidden, not saved): ")
    if not value:
        raise CredentialError("Confluence username/email must not be empty")
    return _validate_username(value)


def _validate_secret_input(value: str, label: str) -> str:
    if len(value) > 16384 or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise CredentialError(f"{label} contains invalid control data")
    return value


def _validate_username(value: str) -> str:
    _validate_secret_input(value, "Confluence username/email")
    if ":" in value:
        raise CredentialError("Confluence username/email must not contain ':'")
    return value


def _build_authorization(
    *,
    auth_scheme: str,
    token: str,
    username: str | None,
) -> str:
    if auth_scheme == "bearer_pat":
        return f"Bearer {token}"
    if auth_scheme == "basic_username_pat":
        if not username:
            raise CredentialError("username is required for basic auth")
        encoded = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"
    raise CredentialError("request profile auth scheme is unsupported")


def _known_scan_identities(
    username: str | None,
    *,
    prompt: bool = False,
) -> tuple[str, ...]:
    values = []
    if username:
        values.append(username)
    configured = os.environ.get("CONFLUENCE_SCAN_IDENTITIES", "")
    values.extend(part.strip() for part in configured.split(",") if part.strip())
    if prompt:
        if not sys.stdin.isatty():
            raise CredentialError(
                "interactive identity scan input requires a terminal"
            )
        entered = getpass.getpass(
            "Known usernames/emails/account IDs to scan (comma-separated, hidden; Enter for none): "
        )
        values.extend(part.strip() for part in entered.split(",") if part.strip())
    return tuple(dict.fromkeys(values))


def _normalize_base_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CredentialError("Confluence base URL must not be empty")
    normalized = value.strip().rstrip("/")
    if _has_unsafe_text(normalized) or any(
        character.isspace() for character in normalized
    ):
        raise CredentialError("Confluence base URL contains unsafe text")
    parts = urlsplit(normalized)
    if parts.scheme != "https":
        raise CredentialError("Confluence base URL must use HTTPS")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise CredentialError("Confluence base URL shape is invalid")
    try:
        parts.port
    except ValueError as exc:
        raise CredentialError("Confluence base URL port is invalid") from exc
    return normalized


def _origin(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname
    if not parts.scheme or not host:
        raise InputError("URL is missing scheme or hostname")
    port = parts.port
    default_port = 443 if parts.scheme == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parts.scheme.lower()}://{host.lower()}{suffix}"


def _path_query_only(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(("", "", parts.path, parts.query, ""))


def _safe_content_type(value: str) -> str:
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type if re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", media_type) else "unknown"


def _is_safe_technical_value(key: str, value: str) -> bool:
    if key not in SAFE_STRING_KEYS:
        return False
    if key == "representation":
        return value in BODY_REPRESENTATION_VALUES
    if key in {"contenttype", "mediatype"}:
        return _safe_content_type(value) != "unknown"
    return value in TECHNICAL_ENUM_VALUES


def _sanitize_timestamp(value: str) -> str:
    if DATE_RE.match(value):
        return "2000-01-01"
    match = TIMESTAMP_RE.match(value)
    if not match:
        return "<SANITIZED_TIMESTAMP>"
    separator = match.group(2)
    fraction = match.group(4) or ""
    zone = match.group(5) or ""
    if fraction:
        fraction = "." + "0" * (len(fraction) - 1)
    if zone == "Z":
        sanitized_zone = "Z"
    elif zone:
        sanitized_zone = "+00:00" if ":" in zone else "+0000"
    else:
        sanitized_zone = ""
    return f"2000-01-01{separator}00:00:00{fraction}{sanitized_zone}"


def _normalize_key(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9_]", "", value.casefold())


def _url_decode_component(value: str) -> str:
    from urllib.parse import unquote

    return unquote(value)


def _contains_unresolved_marker(value: str) -> bool:
    return "<" in value or ">" in value or "REPLACE_WITH" in value


def _has_unsafe_text(value: str) -> bool:
    return (
        len(value) > 4096
        or "`" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _is_forbidden_request_resource(value: str) -> bool:
    candidates = [value]
    decoded = value
    for _ in range(2):
        decoded = _url_decode_component(decoded)
        candidates.extend((decoded, unquote_plus(decoded)))
    for candidate in dict.fromkeys(candidates):
        if BODY_REQUEST_RE.search(candidate) or FORBIDDEN_REQUEST_RESOURCE_RE.search(
            candidate
        ):
            return True
        compact = re.sub(r"[^a-z0-9]", "", candidate.casefold())
        if any(
            token in compact
            for token in (
                "renderedbody",
                "renderedhtml",
                "contentbody",
                "bodystorage",
                "bodyview",
                "bodyexportview",
            )
        ):
            return True
    return False


def _encoded_secret_variants(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    punctuation_encoded = "".join(
        character
        if character.isascii() and (character.isalnum() or character == "-")
        else "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))
        for character in value
    )
    fully_encoded = "".join(f"%{byte:02X}" for byte in value.encode("utf-8"))
    return tuple(
        variant
        for variant in dict.fromkeys(
            (
                quote(value, safe=""),
                quote_plus(value, safe=""),
                punctuation_encoded,
                fully_encoded,
            )
        )
        if variant.casefold() != value.casefold()
    )


def _required_choice(
    mapping: Mapping[str, object],
    key: str,
    choices: set[str],
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value not in choices:
        raise InputError(f"{key} must be one of the documented values")
    return value


def _required_non_placeholder_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if (
        not isinstance(value, str)
        or not value
        or _contains_unresolved_marker(value)
        or _has_unsafe_text(value)
    ):
        raise InputError(f"{key} must be a confirmed non-placeholder string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
