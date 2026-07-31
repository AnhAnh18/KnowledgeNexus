from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ConfluenceRetryAfterState(str, Enum):
    """Observed shape of a Confluence response's Retry-After field."""

    ABSENT = "absent"
    VALID = "valid"
    IGNORED = "ignored"


@dataclass(frozen=True, repr=False)
class ConfluenceRetryAfterMetadata:
    """A sanitized Retry-After observation; never the raw header value."""

    state: ConfluenceRetryAfterState
    delay_seconds: int | float | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ConfluenceRetryAfterState):
            raise TypeError("state expects a ConfluenceRetryAfterState")

        if self.state in (
            ConfluenceRetryAfterState.ABSENT,
            ConfluenceRetryAfterState.IGNORED,
        ):
            if self.delay_seconds is not None:
                raise ValueError(f"{self.state.value} requires delay_seconds is None")
            return

        if isinstance(self.delay_seconds, bool) or type(self.delay_seconds) not in (
            int,
            float,
        ):
            raise TypeError("VALID delay_seconds expects an int or float")
        if self.delay_seconds < 0:
            raise ValueError("VALID delay_seconds must be non-negative")
        if isinstance(self.delay_seconds, float) and not math.isfinite(
            self.delay_seconds
        ):
            raise ValueError("VALID delay_seconds must be finite")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def confluence_retry_after_absent() -> ConfluenceRetryAfterMetadata:
    return ConfluenceRetryAfterMetadata(
        state=ConfluenceRetryAfterState.ABSENT,
        delay_seconds=None,
    )


def confluence_retry_after_ignored() -> ConfluenceRetryAfterMetadata:
    return ConfluenceRetryAfterMetadata(
        state=ConfluenceRetryAfterState.IGNORED,
        delay_seconds=None,
    )


def confluence_retry_after_valid(
    delay_seconds: int | float,
) -> ConfluenceRetryAfterMetadata:
    return ConfluenceRetryAfterMetadata(
        state=ConfluenceRetryAfterState.VALID,
        delay_seconds=delay_seconds,
    )


class ConfluenceHttpFailureKind(str, Enum):
    """Sanitized, stable classification of one observed HTTP transport fact."""

    HTTP_STATUS = "http_status"

    TRANSPORT_TIMEOUT = "transport_timeout"
    CONNECTION_RESET = "connection_reset"
    CONNECTION_ABORTED = "connection_aborted"
    TEMPORARY_CONNECTION_FAILURE = "temporary_connection_failure"
    TEMPORARY_DNS_FAILURE = "temporary_dns_failure"

    UNCLASSIFIED_OS_ERROR = "unclassified_os_error"
    PERMANENT_DNS_FAILURE = "permanent_dns_failure"
    TLS_CERTIFICATE_FAILURE = "tls_certificate_failure"

    REDIRECT_POLICY_FAILURE = "redirect_policy_failure"
    INVALID_URL = "invalid_url"
    INVALID_HTTP_STATUS = "invalid_http_status"

    RESPONSE_TOO_LARGE = "response_too_large"
    MALFORMED_JSON = "malformed_json"
    PAYLOAD_VALIDATION_FAILURE = "payload_validation_failure"


_REDIRECT_STATUS_RANGE = range(300, 400)
_VALID_HTTP_STATUS_RANGE = range(100, 600)


@dataclass(frozen=True, repr=False)
class ConfluenceHttpFailureMetadata:
    """Observed HTTP transport facts only; carries no retry decision."""

    kind: ConfluenceHttpFailureKind
    http_status: int | None
    retry_after: ConfluenceRetryAfterMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConfluenceHttpFailureKind):
            raise TypeError("kind expects a ConfluenceHttpFailureKind")
        if not isinstance(self.retry_after, ConfluenceRetryAfterMetadata):
            raise TypeError("retry_after expects a ConfluenceRetryAfterMetadata")

        if self.kind is ConfluenceHttpFailureKind.HTTP_STATUS:
            if isinstance(self.http_status, bool) or not isinstance(
                self.http_status, int
            ):
                raise TypeError("HTTP_STATUS requires an integer http_status")
            if self.http_status not in _VALID_HTTP_STATUS_RANGE:
                raise ValueError("HTTP_STATUS requires a status between 100 and 599")
            if self.http_status in _REDIRECT_STATUS_RANGE:
                raise ValueError("HTTP_STATUS must not carry a redirect status")
            return

        if self.kind is ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE:
            if isinstance(self.http_status, bool) or not isinstance(
                self.http_status, int
            ):
                raise TypeError(
                    "REDIRECT_POLICY_FAILURE requires an integer http_status"
                )
            if self.http_status not in _REDIRECT_STATUS_RANGE:
                raise ValueError(
                    "REDIRECT_POLICY_FAILURE requires a status between 300 and 399"
                )
            if self.retry_after.state is not ConfluenceRetryAfterState.ABSENT:
                raise ValueError(
                    "REDIRECT_POLICY_FAILURE requires an ABSENT retry_after"
                )
            return

        if self.http_status is not None:
            raise ValueError(f"{self.kind.value} requires http_status is None")
        if self.retry_after.state is not ConfluenceRetryAfterState.ABSENT:
            raise ValueError(f"{self.kind.value} requires an ABSENT retry_after")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
