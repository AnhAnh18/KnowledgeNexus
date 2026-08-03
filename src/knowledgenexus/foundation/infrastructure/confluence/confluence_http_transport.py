from __future__ import annotations

import http.client
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceHttpFailureMetadata,
    ConfluenceRetryAfterMetadata,
    confluence_retry_after_absent,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_failure_mapper import (  # noqa: E501
    _ConfluenceRetryAfterHeaderInterfaceError,
    classify_confluence_transport_exception,
    extract_confluence_retry_after,
)


DEFAULT_CONFLUENCE_TIMEOUT_SECONDS = 30.0
DEFAULT_CONFLUENCE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ConfluenceHttpError(RuntimeError):
    """A safe, body-free failure from the focused Confluence JSON transport."""

    def __init__(
        self,
        message: str,
        *,
        metadata: ConfluenceHttpFailureMetadata | None = None,
    ) -> None:
        super().__init__(message)
        if metadata is not None and not isinstance(
            metadata, ConfluenceHttpFailureMetadata
        ):
            raise TypeError("metadata expects a ConfluenceHttpFailureMetadata")
        self._metadata = metadata

    @property
    def metadata(self) -> ConfluenceHttpFailureMetadata | None:
        """Return immutable-by-interface structured failure facts."""

        return self._metadata


class ConfluenceHttpResponseTooLargeError(ConfluenceHttpError):
    """The response body exceeded the configured size limit.

    A subclass of ConfluenceHttpError so existing `except ConfluenceHttpError`
    handlers keep catching it, while callers that care can distinguish it.
    """


@dataclass(frozen=True, repr=False)
class ConfluenceHttpResponse:
    """HTTP status plus exact response bytes for status-aware observations."""

    status_code: int
    body: bytes
    retry_after: ConfluenceRetryAfterMetadata = confluence_retry_after_absent()

    def __post_init__(self) -> None:
        _require_http_status(self.status_code)
        if not isinstance(self.body, bytes):
            raise TypeError("body expects bytes")
        if not isinstance(self.retry_after, ConfluenceRetryAfterMetadata):
            raise TypeError("retry_after expects a ConfluenceRetryAfterMetadata")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class PreparedConfluenceGetInput:
    """Validated, immutable input reused across retry attempts."""

    path: str
    query_pairs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _require_request_path(self.path)
        if not isinstance(self.query_pairs, tuple):
            raise TypeError("query_pairs expects a tuple")
        for pair in self.query_pairs:
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or not all(isinstance(item, str) for item in pair)
            ):
                raise TypeError("query_pairs expects tuples of strings")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def prepare_confluence_get_input(
    *, path: object, query: object
) -> PreparedConfluenceGetInput:
    """Validate and snapshot caller input before pacing or accounting."""

    return PreparedConfluenceGetInput(
        path=_require_request_path(path),
        query_pairs=_copy_query_pairs(query),
    )


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

    def get_response_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> ConfluenceHttpResponse: ...


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
                "Confluence GET returned malformed JSON",
                metadata=_failure_metadata(ConfluenceHttpFailureKind.MALFORMED_JSON),
            ) from None
        if not isinstance(payload, Mapping):
            raise ConfluenceHttpError(
                "Confluence GET returned a non-object JSON payload",
                metadata=_payload_validation_metadata(),
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

    def get_response_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> ConfluenceHttpResponse:
        """Return exact bytes for both success and expected non-2xx responses.

        This additive seam exists for endpoints where 401/403/404 are
        observations. Redirects, network failures, and size-limit failures stay
        transport errors and therefore can never masquerade as unavailable data.
        Content type is intentionally not constrained because an expected 404
        body may be empty, JSON, or HTML and must be preserved exactly.
        """
        prepared = prepare_confluence_get_input(path=path, query=query)
        return self._get_response_bytes_prepared(prepared)

    def _get_response_bytes_prepared(
        self,
        prepared: PreparedConfluenceGetInput,
        *,
        on_attempt_start: Callable[[], None] | None = None,
    ) -> ConfluenceHttpResponse:
        request = self._build_request_prepared(prepared)
        if on_attempt_start is not None:
            on_attempt_start()
        try:
            with self._opener.open(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = _require_http_status(getattr(response, "status", None))
                if 300 <= status < 400:
                    raise ConfluenceHttpError(
                        f"Confluence GET returned HTTP status {status}",
                        metadata=_redirect_metadata(status),
                    )
                body = self._read_bounded_body(response)
                retry_after = self._extract_retry_after(
                    getattr(response, "headers", None)
                )
        except urllib.error.HTTPError as exc:
            try:
                status = _require_http_status(exc.code)
                if 300 <= status < 400:
                    raise ConfluenceHttpError(
                        f"Confluence GET returned HTTP status {status}",
                        metadata=_redirect_metadata(status),
                    ) from None
                try:
                    body = (
                        self._read_bounded_body(exc) if exc.fp is not None else b""
                    )
                except ConfluenceHttpResponseTooLargeError:
                    raise
                except ConfluenceHttpError:
                    raise
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                    http.client.HTTPException,
                ) as read_exc:
                    raise ConfluenceHttpError(
                        "Confluence GET failed",
                        metadata=_operational_metadata(read_exc),
                    ) from None
                except (UnicodeError, ValueError):
                    raise ConfluenceHttpError(
                        "Confluence GET failed",
                        metadata=_payload_validation_metadata(),
                    ) from None
                retry_after = self._extract_retry_after(exc.headers)
            finally:
                exc.close()
        except ConfluenceHttpError:
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            raise ConfluenceHttpError(
                "Confluence GET failed",
                metadata=_operational_metadata(exc),
            ) from None
        except (UnicodeError, ValueError):
            raise ConfluenceHttpError(
                "Confluence GET failed",
                metadata=_payload_validation_metadata(),
            ) from None
        return ConfluenceHttpResponse(
            status_code=status,
            body=body,
            retry_after=retry_after,
        )

    def _read_response_bytes(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> bytes:
        prepared = prepare_confluence_get_input(path=path, query=query)
        return self._read_response_bytes_prepared(prepared)

    def _read_response_bytes_prepared(
        self,
        prepared: PreparedConfluenceGetInput,
        *,
        on_attempt_start: Callable[[], None] | None = None,
    ) -> bytes:
        request = self._build_request_prepared(prepared)
        if on_attempt_start is not None:
            on_attempt_start()

        try:
            with self._opener.open(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = _require_http_status(getattr(response, "status", None))
                if 300 <= status < 400:
                    raise ConfluenceHttpError(
                        f"Confluence GET returned HTTP status {status}",
                        metadata=_redirect_metadata(status),
                    )
                if status < 200 or status >= 300:
                    raise ConfluenceHttpError(
                        f"Confluence GET returned HTTP status {status}",
                        metadata=ConfluenceHttpFailureMetadata(
                            kind=ConfluenceHttpFailureKind.HTTP_STATUS,
                            http_status=status,
                            retry_after=self._extract_retry_after(
                                getattr(response, "headers", None)
                            ),
                        ),
                    )
                _require_json_content_type(response.headers)
                body = self._read_bounded_body(response)
        except urllib.error.HTTPError as exc:
            status = _require_http_status(exc.code)
            if 300 <= status < 400:
                raise ConfluenceHttpError(
                    f"Confluence GET returned HTTP status {status}",
                    metadata=_redirect_metadata(status),
                ) from None
            raise ConfluenceHttpError(
                f"Confluence GET returned HTTP status {status}",
                metadata=ConfluenceHttpFailureMetadata(
                    kind=ConfluenceHttpFailureKind.HTTP_STATUS,
                    http_status=status,
                    retry_after=self._extract_retry_after(exc.headers),
                ),
            ) from None
        except ConfluenceHttpError:
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            raise ConfluenceHttpError(
                "Confluence GET failed",
                metadata=_operational_metadata(exc),
            ) from None
        except (UnicodeError, ValueError):
            raise ConfluenceHttpError(
                "Confluence GET failed",
                metadata=_payload_validation_metadata(),
            ) from None

        return body

    def _build_request(
        self,
        *,
        path: str,
        query: Mapping[str, str],
    ) -> urllib.request.Request:
        prepared = prepare_confluence_get_input(path=path, query=query)
        return self._build_request_prepared(prepared)

    def _build_request_prepared(
        self, prepared: PreparedConfluenceGetInput
    ) -> urllib.request.Request:
        request_path = prepared.path
        query_pairs = prepared.query_pairs
        encoded_query = urllib.parse.urlencode(query_pairs)
        url = f"{self._base_url}/{request_path.lstrip('/')}?{encoded_query}"
        try:
            return urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._personal_access_token}",
                },
                method="GET",
            )
        except (UnicodeError, ValueError):
            raise ConfluenceHttpError(
                "Confluence GET request could not be constructed",
                metadata=_failure_metadata(ConfluenceHttpFailureKind.INVALID_URL),
            ) from None

    def _read_bounded_body(self, response: object) -> bytes:
        read = getattr(response, "read", None)
        if not callable(read):
            raise ConfluenceHttpError(
                "Confluence GET returned an invalid body type",
                metadata=_payload_validation_metadata(),
            )
        body = read(self._max_response_bytes + 1)
        if not isinstance(body, bytes):
            raise ConfluenceHttpError(
                "Confluence GET returned an invalid body type",
                metadata=_payload_validation_metadata(),
            )
        if len(body) > self._max_response_bytes:
            raise ConfluenceHttpResponseTooLargeError(
                "Confluence GET exceeded the response size limit",
                metadata=_failure_metadata(ConfluenceHttpFailureKind.RESPONSE_TOO_LARGE),
            )
        return body

    def _extract_retry_after(self, headers: object) -> ConfluenceRetryAfterMetadata:
        try:
            return extract_confluence_retry_after(headers, datetime.now(timezone.utc))
        except _ConfluenceRetryAfterHeaderInterfaceError:
            raise ConfluenceHttpError(
                "Confluence GET returned invalid response headers",
                metadata=_payload_validation_metadata(),
            ) from None


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


def _require_http_status(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfluenceHttpError(
            "Confluence GET returned an invalid HTTP status",
            metadata=_failure_metadata(ConfluenceHttpFailureKind.INVALID_HTTP_STATUS),
        )
    if value < 100 or value > 599:
        raise ConfluenceHttpError(
            "Confluence GET returned an invalid HTTP status",
            metadata=_failure_metadata(ConfluenceHttpFailureKind.INVALID_HTTP_STATUS),
        )
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
        raise ConfluenceHttpError(
            "Confluence GET returned invalid response headers",
            metadata=_payload_validation_metadata(),
        )
    raw_content_type = get_header("Content-Type")
    if raw_content_type is None:
        return
    if not isinstance(raw_content_type, str):
        raise ConfluenceHttpError(
            "Confluence GET returned invalid response headers",
            metadata=_payload_validation_metadata(),
        )
    media_type = raw_content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ConfluenceHttpError(
            "Confluence GET returned a non-JSON content type",
            metadata=_payload_validation_metadata(),
        )


def _failure_metadata(kind: ConfluenceHttpFailureKind) -> ConfluenceHttpFailureMetadata:
    return ConfluenceHttpFailureMetadata(
        kind=kind,
        http_status=None,
        retry_after=confluence_retry_after_absent(),
    )


def _payload_validation_metadata() -> ConfluenceHttpFailureMetadata:
    return _failure_metadata(ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE)


def _redirect_metadata(status: int) -> ConfluenceHttpFailureMetadata:
    return ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE,
        http_status=status,
        retry_after=confluence_retry_after_absent(),
    )


def _operational_metadata(exc: BaseException) -> ConfluenceHttpFailureMetadata:
    return ConfluenceHttpFailureMetadata(
        kind=classify_confluence_transport_exception(exc),
        http_status=None,
        retry_after=confluence_retry_after_absent(),
    )
