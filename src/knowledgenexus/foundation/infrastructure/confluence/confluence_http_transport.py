from __future__ import annotations

import http.client
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Protocol


DEFAULT_CONFLUENCE_TIMEOUT_SECONDS = 30.0
DEFAULT_CONFLUENCE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ConfluenceHttpError(RuntimeError):
    """A safe, body-free failure from the focused Confluence JSON transport."""


class ConfluenceHttpTransport(Protocol):
    """Minimal synchronous JSON GET seam used by the Data Center adapter."""

    def get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> Mapping[str, object]: ...

    def get_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> bytes: ...


class UrllibConfluenceHttpTransport:
    """HTTPS-only, redirect-refusing Bearer-PAT JSON transport."""

    def __init__(
        self,
        *,
        base_url: str,
        personal_access_token: str,
        timeout_seconds: float = DEFAULT_CONFLUENCE_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_CONFLUENCE_MAX_RESPONSE_BYTES,
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._personal_access_token = _require_personal_access_token(
            personal_access_token
        )
        self._timeout_seconds = _require_timeout_seconds(timeout_seconds)
        self._max_response_bytes = _require_max_response_bytes(max_response_bytes)
        self._opener = urllib.request.build_opener(_RefuseRedirectHandler())

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> Mapping[str, object]:
        body = self._read_response_bytes(path=path, query=query)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ConfluenceHttpError(
                "Confluence GET returned malformed JSON"
            ) from None
        if not isinstance(payload, Mapping):
            raise ConfluenceHttpError(
                "Confluence GET returned a non-object JSON payload"
            )
        return payload

    def get_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> bytes:
        """Return the exact response-body bytes, before any JSON parsing.

        Same HTTPS, redirect, status, content-type, and size guards as
        `get_json`; only the trailing `json.loads` is omitted so a caller can
        preserve the response verbatim.
        """
        return self._read_response_bytes(path=path, query=query)

    def _read_response_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> bytes:
        request_path = _require_request_path(path)
        query_pairs = _copy_query_pairs(query)
        url = (
            f"{self._base_url}/{request_path.lstrip('/')}"
            f"?{urllib.parse.urlencode(query_pairs)}"
        )
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._personal_access_token}",
                },
                method="GET",
            )
        except (UnicodeError, ValueError):
            raise ConfluenceHttpError(
                "Confluence GET request could not be constructed"
            ) from None

        try:
            with self._opener.open(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = getattr(response, "status", None)
                if isinstance(status, bool) or not isinstance(status, int):
                    raise ConfluenceHttpError(
                        "Confluence GET returned an invalid HTTP status"
                    )
                if status < 200 or status >= 300:
                    raise ConfluenceHttpError(
                        f"Confluence GET returned HTTP status {status}"
                    )
                _require_json_content_type(response.headers)
                body = response.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ConfluenceHttpError(
                f"Confluence GET returned HTTP status {exc.code}"
            ) from None
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
            UnicodeError,
            ValueError,
        ):
            raise ConfluenceHttpError("Confluence GET failed") from None

        if not isinstance(body, bytes):
            raise ConfluenceHttpError("Confluence GET returned an invalid body type")
        if len(body) > self._max_response_bytes:
            raise ConfluenceHttpError(
                "Confluence GET exceeded the response size limit"
            )
        return body


class _RefuseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


def _normalize_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("base_url expects a string")
    if value == "":
        raise ValueError("base_url must not be empty")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("base_url must not contain whitespace or control characters")

    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError("base_url must be a valid HTTPS URL") from None

    if parsed.scheme.lower() != "https":
        raise ValueError("base_url must use https")
    if hostname is None or hostname == "":
        raise ValueError("base_url must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain user-info")
    if parsed.query != "" or parsed.fragment != "":
        raise ValueError("base_url must not contain a query or fragment")
    return value.rstrip("/")


def _require_personal_access_token(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("personal_access_token expects a string")
    if value == "":
        raise ValueError("personal_access_token must not be empty")
    if "\r" in value or "\n" in value:
        raise ValueError("personal_access_token must not contain line breaks")
    return value


def _require_timeout_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout_seconds expects a number")
    timeout_seconds = float(value)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    return timeout_seconds


def _require_max_response_bytes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_response_bytes expects an integer")
    if value <= 0:
        raise ValueError("max_response_bytes must be positive")
    return value


def _require_request_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("path expects a string")
    parsed = urllib.parse.urlsplit(value)
    if (
        value == ""
        or not value.startswith("/")
        or parsed.scheme != ""
        or parsed.netloc != ""
        or parsed.query != ""
        or parsed.fragment != ""
    ):
        raise ValueError("path must be an absolute-path reference without a query")
    return value


def _copy_query_pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise TypeError("query expects a mapping of strings")
    pairs = tuple(value.items())
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in pairs):
        raise TypeError("query expects string keys and values")
    return pairs


def _require_json_content_type(headers: object) -> None:
    get_header = getattr(headers, "get", None)
    if not callable(get_header):
        raise ConfluenceHttpError("Confluence GET returned invalid response headers")
    raw_content_type = get_header("Content-Type")
    if raw_content_type is None:
        return
    if not isinstance(raw_content_type, str):
        raise ConfluenceHttpError("Confluence GET returned invalid response headers")
    media_type = raw_content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ConfluenceHttpError(
            "Confluence GET returned a non-JSON content type"
        )
