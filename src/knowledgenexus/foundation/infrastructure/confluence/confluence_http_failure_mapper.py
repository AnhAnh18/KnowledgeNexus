from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceRetryAfterMetadata,
    confluence_retry_after_absent,
    confluence_retry_after_ignored,
    confluence_retry_after_valid,
)

MAX_URLERROR_UNWRAP_DEPTH = 8

_RETRY_AFTER_HEADER = "Retry-After"
_DELTA_SECONDS_DIGITS = frozenset("0123456789")


class _ConfluenceRetryAfterHeaderInterfaceError(Exception):
    """Internal-only signal that the response-header interface was invalid.

    Never exposed to callers of this package; the transport converts this
    into the existing safe ``ConfluenceHttpError`` message.
    """


class _UnclassifiedTransportFailure:
    """Sentinel returned by URLError unwrapping when classification stops."""


_UNCLASSIFIED = _UnclassifiedTransportFailure()


def extract_confluence_retry_after(
    headers: object | None,
    now_utc: datetime,
) -> ConfluenceRetryAfterMetadata:
    """Return a sanitized Retry-After observation for one HTTP response.

    Raises ``_ConfluenceRetryAfterHeaderInterfaceError`` when the header
    collection interface itself is invalid; raises ``TypeError`` or
    ``ValueError`` when ``now_utc`` is not a timezone-aware UTC datetime
    (programmer misuse, not an observed HTTP fact).
    """
    _require_utc_now(now_utc)

    if headers is None:
        return confluence_retry_after_absent()

    get_all = getattr(headers, "get_all", None)
    if not callable(get_all):
        raise _ConfluenceRetryAfterHeaderInterfaceError(
            "headers.get_all is missing or not callable"
        )

    try:
        values = get_all(_RETRY_AFTER_HEADER, ())
    except Exception:
        raise _ConfluenceRetryAfterHeaderInterfaceError(
            "headers.get_all raised while reading Retry-After"
        ) from None

    if not isinstance(values, (list, tuple)):
        raise _ConfluenceRetryAfterHeaderInterfaceError(
            "headers.get_all returned an unsupported container"
        )
    if not all(isinstance(value, str) for value in values):
        raise _ConfluenceRetryAfterHeaderInterfaceError(
            "headers.get_all returned a non-string Retry-After value"
        )

    if len(values) == 0:
        return confluence_retry_after_absent()
    if len(values) > 1:
        return confluence_retry_after_ignored()

    return _parse_retry_after_field(values[0], now_utc)


def _require_utc_now(value: object) -> None:
    if not isinstance(value, datetime):
        raise TypeError("now_utc expects a datetime")
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("now_utc must be timezone-aware")
    if offset != timedelta(0):
        raise ValueError("now_utc must use a zero UTC offset")


def _parse_retry_after_field(
    field: str,
    now_utc: datetime,
) -> ConfluenceRetryAfterMetadata:
    if "\r" in field or "\n" in field:
        return confluence_retry_after_ignored()

    stripped = field.strip(" \t")
    if stripped == "":
        return confluence_retry_after_ignored()

    if set(stripped) <= _DELTA_SECONDS_DIGITS:
        try:
            delay_seconds = int(stripped)
        except ValueError:
            # Python limits decimal-to-int conversion length. A server-controlled
            # field must not escape the sanitized transport taxonomy when it
            # exceeds that interpreter limit.
            return confluence_retry_after_ignored()
        return confluence_retry_after_valid(delay_seconds)

    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return confluence_retry_after_ignored()
    if parsed is None or parsed.tzinfo is None:
        return confluence_retry_after_ignored()

    parsed_utc = parsed.astimezone(timezone.utc)
    delay_seconds = max(0.0, (parsed_utc - now_utc).total_seconds())
    return confluence_retry_after_valid(delay_seconds)


def classify_confluence_transport_exception(
    exc: BaseException,
) -> ConfluenceHttpFailureKind:
    """Map one operational transport exception to a stable failure kind.

    Callers must handle ``urllib.error.HTTPError`` as an observed HTTP status
    before reaching this function; it never converts an HTTPError into
    ``HTTP_STATUS`` metadata.
    """
    if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
        raise exc

    if isinstance(exc, urllib.error.HTTPError):
        target: object = _UNCLASSIFIED
    elif isinstance(exc, urllib.error.URLError):
        target = _unwrap_url_error(exc)
    else:
        target = exc

    return _classify_operational_exception(target)


def _unwrap_url_error(top_exc: urllib.error.URLError) -> object:
    seen_ids: set[int] = set()
    current: urllib.error.URLError = top_exc
    hops = 0

    while True:
        if id(current) in seen_ids:
            return _UNCLASSIFIED
        seen_ids.add(id(current))

        reason = current.reason
        hops += 1
        if hops > MAX_URLERROR_UNWRAP_DEPTH:
            return _UNCLASSIFIED
        if isinstance(reason, urllib.error.HTTPError):
            return _UNCLASSIFIED
        if not isinstance(reason, BaseException):
            return _UNCLASSIFIED
        if isinstance(reason, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise reason

        if not isinstance(reason, urllib.error.URLError):
            return reason
        current = reason


def _classify_operational_exception(
    exc: object,
) -> ConfluenceHttpFailureKind:
    if isinstance(exc, http.client.RemoteDisconnected):
        return ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ConfluenceHttpFailureKind.TLS_CERTIFICATE_FAILURE
    if isinstance(exc, socket.gaierror):
        if getattr(exc, "errno", None) == socket.EAI_AGAIN:
            return ConfluenceHttpFailureKind.TEMPORARY_DNS_FAILURE
        return ConfluenceHttpFailureKind.PERMANENT_DNS_FAILURE
    if isinstance(exc, TimeoutError):
        return ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT
    if isinstance(exc, ConnectionResetError):
        return ConfluenceHttpFailureKind.CONNECTION_RESET
    if isinstance(exc, ConnectionAbortedError):
        return ConfluenceHttpFailureKind.CONNECTION_ABORTED
    if isinstance(exc, ConnectionRefusedError):
        return ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    if isinstance(exc, BrokenPipeError):
        return ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    if isinstance(exc, http.client.IncompleteRead):
        return ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    return ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
