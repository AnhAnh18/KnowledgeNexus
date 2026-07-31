from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
from datetime import datetime, timedelta, timezone
from email.message import Message

import pytest

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceRetryAfterState,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_failure_mapper import (  # noqa: E501
    MAX_URLERROR_UNWRAP_DEPTH,
    _ConfluenceRetryAfterHeaderInterfaceError,
    classify_confluence_transport_exception,
    extract_confluence_retry_after,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _headers(*values: str) -> Message:
    message = Message()
    for value in values:
        message["Retry-After"] = value
    return message


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------


def test_headers_none_is_absent() -> None:
    result = extract_confluence_retry_after(None, NOW)
    assert result.state is ConfluenceRetryAfterState.ABSENT


def test_no_retry_after_header_is_absent() -> None:
    result = extract_confluence_retry_after(Message(), NOW)
    assert result.state is ConfluenceRetryAfterState.ABSENT


def test_decimal_zero_is_valid() -> None:
    result = extract_confluence_retry_after(_headers("0"), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == 0


def test_decimal_thirty_is_valid() -> None:
    result = extract_confluence_retry_after(_headers("30"), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == 30


def test_leading_trailing_sp_htab_accepted() -> None:
    result = extract_confluence_retry_after(_headers(" \t30\t "), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == 30


@pytest.mark.parametrize(
    "value",
    ("+30", "-30", "30.5", "30 seconds", "30,", "abc", "30x"),
)
def test_invalid_decimal_forms_are_ignored(value: str) -> None:
    result = extract_confluence_retry_after(_headers(value), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED


def test_embedded_cr_lf_ignored() -> None:
    result = extract_confluence_retry_after(_headers("30\r\nInjected: x"), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED


def test_very_large_decimal_remains_valid_uncapped() -> None:
    huge = "9" * 30
    result = extract_confluence_retry_after(_headers(huge), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == int(huge)


def test_decimal_beyond_interpreter_integer_limit_is_ignored() -> None:
    result = extract_confluence_retry_after(_headers("9" * 5000), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED
    assert result.delay_seconds is None


def test_future_http_date_is_valid() -> None:
    future = NOW + timedelta(seconds=120)
    header_value = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    result = extract_confluence_retry_after(_headers(header_value), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == pytest.approx(120.0)


def test_past_http_date_yields_exact_zero() -> None:
    past = NOW - timedelta(seconds=120)
    header_value = past.strftime("%a, %d %b %Y %H:%M:%S GMT")
    result = extract_confluence_retry_after(_headers(header_value), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == 0.0


def test_future_date_with_fractional_difference_preserves_fraction() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, 500_000, tzinfo=timezone.utc)
    future = datetime(2026, 1, 1, 0, 1, 0, 0, tzinfo=timezone.utc)
    header_value = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    result = extract_confluence_retry_after(_headers(header_value), now)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == pytest.approx(59.5)


def test_timezone_conversion_is_exact() -> None:
    header_value = "Thu, 01 Jan 2026 05:00:00 +0500"
    result = extract_confluence_retry_after(_headers(header_value), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == pytest.approx(0.0)


def test_naive_parsed_date_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    import knowledgenexus.foundation.infrastructure.confluence.confluence_http_failure_mapper as mapper_module

    monkeypatch.setattr(
        mapper_module,
        "parsedate_to_datetime",
        lambda value: datetime(2026, 1, 1),
    )
    result = extract_confluence_retry_after(_headers("Thu, 01 Jan 2026 00:00:00 GMT"), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED


def test_invalid_date_ignored() -> None:
    result = extract_confluence_retry_after(_headers("not a date at all"), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED


def test_http_date_comma_not_split() -> None:
    header_value = "Thu, 01 Jan 2026 00:00:10 GMT"
    result = extract_confluence_retry_after(_headers(header_value), NOW)
    assert result.state is ConfluenceRetryAfterState.VALID
    assert result.delay_seconds == pytest.approx(10.0)


def test_duplicate_field_instances_ignored() -> None:
    result = extract_confluence_retry_after(_headers("30", "60"), NOW)
    assert result.state is ConfluenceRetryAfterState.IGNORED


def test_missing_get_all_is_payload_validation_failure() -> None:
    class NoGetAll:
        pass

    with pytest.raises(_ConfluenceRetryAfterHeaderInterfaceError):
        extract_confluence_retry_after(NoGetAll(), NOW)


def test_non_callable_get_all_is_payload_validation_failure() -> None:
    class BadGetAll:
        get_all = "not callable"

    with pytest.raises(_ConfluenceRetryAfterHeaderInterfaceError):
        extract_confluence_retry_after(BadGetAll(), NOW)


def test_get_all_raising_is_payload_validation_failure_with_no_leaked_cause() -> None:
    class Raising:
        def get_all(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("private synthetic failure detail")

    with pytest.raises(_ConfluenceRetryAfterHeaderInterfaceError) as exc_info:
        extract_confluence_retry_after(Raising(), NOW)
    assert exc_info.value.__cause__ is None
    assert "private synthetic failure detail" not in str(exc_info.value)


def test_get_all_wrong_container_is_payload_validation_failure() -> None:
    class WrongContainer:
        def get_all(self, *args: object, **kwargs: object) -> object:
            return "30"

    with pytest.raises(_ConfluenceRetryAfterHeaderInterfaceError):
        extract_confluence_retry_after(WrongContainer(), NOW)


def test_get_all_non_string_member_is_payload_validation_failure() -> None:
    class NonStringMember:
        def get_all(self, *args: object, **kwargs: object) -> object:
            return (30,)

    with pytest.raises(_ConfluenceRetryAfterHeaderInterfaceError):
        extract_confluence_retry_after(NonStringMember(), NOW)


def test_naive_now_utc_raises() -> None:
    with pytest.raises((TypeError, ValueError)):
        extract_confluence_retry_after(None, datetime(2026, 1, 1))


def test_non_utc_now_raises() -> None:
    with pytest.raises((TypeError, ValueError)):
        extract_confluence_retry_after(
            None,
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5))),
        )


def test_non_datetime_now_raises() -> None:
    with pytest.raises(TypeError):
        extract_confluence_retry_after(None, "2026-01-01")  # type: ignore[arg-type]


def test_raw_header_value_never_appears_in_repr_or_error_text() -> None:
    secret_marker = "super-secret-header-value-marker"
    result = extract_confluence_retry_after(_headers(secret_marker), NOW)
    assert secret_marker not in repr(result)
    assert secret_marker not in str(result)


# ---------------------------------------------------------------------------
# URLError / exception precedence
# ---------------------------------------------------------------------------


def test_remote_disconnected_before_connection_reset() -> None:
    exc = http.client.RemoteDisconnected("gone")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    )


def test_certificate_failure_before_generic_oserror() -> None:
    exc = ssl.SSLCertVerificationError("bad cert")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.TLS_CERTIFICATE_FAILURE
    )


def test_gaierror_temporary_before_generic_oserror() -> None:
    exc = socket.gaierror(socket.EAI_AGAIN, "temp")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.TEMPORARY_DNS_FAILURE
    )


def test_gaierror_other_is_permanent_dns_failure() -> None:
    exc = socket.gaierror(socket.EAI_NONAME, "permanent")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.PERMANENT_DNS_FAILURE
    )


def test_timeout_error() -> None:
    assert (
        classify_confluence_transport_exception(TimeoutError())
        == ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT
    )


def test_connection_reset() -> None:
    assert (
        classify_confluence_transport_exception(ConnectionResetError())
        == ConfluenceHttpFailureKind.CONNECTION_RESET
    )


def test_connection_aborted() -> None:
    assert (
        classify_confluence_transport_exception(ConnectionAbortedError())
        == ConfluenceHttpFailureKind.CONNECTION_ABORTED
    )


def test_connection_refused() -> None:
    assert (
        classify_confluence_transport_exception(ConnectionRefusedError())
        == ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    )


def test_broken_pipe() -> None:
    assert (
        classify_confluence_transport_exception(BrokenPipeError())
        == ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    )


def test_incomplete_read() -> None:
    exc = http.client.IncompleteRead(b"")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE
    )


def test_generic_oserror() -> None:
    assert (
        classify_confluence_transport_exception(OSError("generic"))
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


def test_generic_http_exception() -> None:
    assert (
        classify_confluence_transport_exception(http.client.HTTPException("generic"))
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


@pytest.mark.parametrize(
    "reason,expected",
    [
        (ConnectionResetError(), ConfluenceHttpFailureKind.CONNECTION_RESET),
        (TimeoutError(), ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT),
        (
            socket.gaierror(socket.EAI_AGAIN, "temp"),
            ConfluenceHttpFailureKind.TEMPORARY_DNS_FAILURE,
        ),
    ],
)
def test_url_error_wraps_typed_reason(
    reason: BaseException, expected: ConfluenceHttpFailureKind
) -> None:
    exc = urllib.error.URLError(reason)
    assert classify_confluence_transport_exception(exc) == expected


def test_url_error_with_string_reason_is_unclassified() -> None:
    exc = urllib.error.URLError("plain string reason")
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


def test_nested_chain_within_depth_resolves_typed_reason() -> None:
    innermost = ConnectionResetError()
    current: BaseException = innermost
    for _ in range(MAX_URLERROR_UNWRAP_DEPTH - 1):
        current = urllib.error.URLError(current)
    top = urllib.error.URLError(current)
    assert (
        classify_confluence_transport_exception(top)
        == ConfluenceHttpFailureKind.CONNECTION_RESET
    )


def test_chain_requiring_ninth_hop_is_unclassified() -> None:
    current: BaseException = ConnectionResetError()
    for _ in range(MAX_URLERROR_UNWRAP_DEPTH + 1):
        current = urllib.error.URLError(current)
    assert (
        classify_confluence_transport_exception(current)
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


def test_self_cycle_is_unclassified() -> None:
    exc = urllib.error.URLError("placeholder")
    exc.reason = exc
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


def test_two_object_cycle_is_unclassified() -> None:
    a = urllib.error.URLError("a")
    b = urllib.error.URLError("b")
    a.reason = b
    b.reason = a
    assert (
        classify_confluence_transport_exception(a)
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


def test_nested_http_error_reason_is_unclassified() -> None:
    nested_http_error = urllib.error.HTTPError(
        "https://fixture.invalid", 500, "err", hdrs=None, fp=None
    )
    exc = urllib.error.URLError(nested_http_error)
    assert (
        classify_confluence_transport_exception(exc)
        == ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR
    )


@pytest.mark.parametrize(
    "signal_exc", (KeyboardInterrupt(), SystemExit(), GeneratorExit())
)
def test_wrapped_operator_interruption_propagates_unchanged(
    signal_exc: BaseException,
) -> None:
    exc = urllib.error.URLError(signal_exc)
    with pytest.raises(type(signal_exc)) as exc_info:
        classify_confluence_transport_exception(exc)
    assert exc_info.value is signal_exc


def test_no_original_message_appears_in_str_or_repr() -> None:
    secret = "private-synthetic-network-detail"
    exc = urllib.error.URLError(OSError(secret))
    kind = classify_confluence_transport_exception(exc)
    assert secret not in str(kind)
    assert secret not in repr(kind)
