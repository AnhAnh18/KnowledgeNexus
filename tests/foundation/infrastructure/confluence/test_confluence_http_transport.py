from __future__ import annotations

import urllib.error
import urllib.request
from io import BytesIO
from email.message import Message
from typing import Any

import pytest

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceRetryAfterState,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    ConfluenceHttpResponseTooLargeError,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)


BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"


class FakeResponse:
    def __init__(
        self,
        *,
        body: bytes = b'{"ok":true}',
        status: int = 200,
        content_type: str | None = "application/json; charset=utf-8",
    ) -> None:
        self.body = body
        self.status = status
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        self.read_limits: list[int] = []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return self.body[:limit]


class RecordingOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> Any:
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_error_metadata_is_read_only() -> None:
    metadata = transport_module._failure_metadata(
        ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT
    )
    error = ConfluenceHttpError("Confluence GET failed", metadata=metadata)

    with pytest.raises(AttributeError):
        error.metadata = None  # type: ignore[misc]

    assert error.metadata is metadata


def test_https_get_preserves_context_path_and_sets_safe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse()
    transport, opener, handlers = _transport(monkeypatch, response=response)

    payload = transport.get_json(
        path="/rest/api/search",
        query={"cql": 'space="SPACE" and ancestor=1000', "start": "0"},
    )

    assert payload == {"ok": True}
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.get_method() == "GET"
    assert request.full_url == (
        "https://fixture.invalid/confluence/rest/api/search?"
        "cql=space%3D%22SPACE%22+and+ancestor%3D1000&start=0"
    )
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Authorization") == f"Bearer {PAT}"
    assert request.get_header("Cookie") is None
    assert timeout == 12.5
    assert response.read_limits == [1025]
    assert len(handlers) == 1
    assert isinstance(handlers[0], transport_module._RefuseRedirectHandler)


@pytest.mark.parametrize(
    "base_url",
    (
        "http://fixture.invalid",
        "https:///confluence",
        "https://user@fixture.invalid",
        "https://user:password@fixture.invalid",
        "https://fixture.invalid?query=value",
        "https://fixture.invalid#fragment",
        "https://fixture.invalid/path with space",
    ),
)
def test_rejects_unsafe_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        UrllibConfluenceHttpTransport(
            base_url=base_url,
            personal_access_token=PAT,
        )


def test_rejects_non_string_or_empty_base_url() -> None:
    with pytest.raises(TypeError):
        UrllibConfluenceHttpTransport(
            base_url=1,  # type: ignore[arg-type]
            personal_access_token=PAT,
        )
    with pytest.raises(ValueError):
        UrllibConfluenceHttpTransport(
            base_url="",
            personal_access_token=PAT,
        )


def test_rejects_empty_or_non_string_pat() -> None:
    with pytest.raises(ValueError):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token="",
        )
    with pytest.raises(TypeError):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=1,  # type: ignore[arg-type]
        )


def test_rejects_pat_header_injection_without_disclosing_value() -> None:
    unsafe_pat = "fixture-secret\r\nCookie: stolen"

    with pytest.raises(ValueError) as exc_info:
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=unsafe_pat,
        )

    assert unsafe_pat not in str(exc_info.value)
    assert "Cookie: stolen" not in str(exc_info.value)


def test_repr_does_not_disclose_pat_or_hostname() -> None:
    transport = UrllibConfluenceHttpTransport(
        base_url=BASE_URL,
        personal_access_token=PAT,
    )

    rendered = repr(transport)

    assert PAT not in rendered
    assert "fixture.invalid" not in rendered


@pytest.mark.parametrize(
    "timeout_seconds",
    (0, -1, float("nan"), float("inf"), float("-inf")),
)
def test_rejects_non_finite_or_non_positive_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize("timeout_seconds", (True, "30"))
def test_rejects_non_numeric_timeout(timeout_seconds: object) -> None:
    with pytest.raises(TypeError, match="expects a number"):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("max_response_bytes", (0, -1))
def test_rejects_non_positive_response_limit(max_response_bytes: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            max_response_bytes=max_response_bytes,
        )


@pytest.mark.parametrize("max_response_bytes", (True, 10.0, "10"))
def test_rejects_non_integer_response_limit(max_response_bytes: object) -> None:
    with pytest.raises(TypeError, match="expects an integer"):
        UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            max_response_bytes=max_response_bytes,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "path",
    (
        "rest/api/search",
        "//other.invalid/rest/api/search",
        "https://other.invalid/rest/api/search",
        "/rest/api/search?start=0",
        "/rest/api/search#fragment",
    ),
)
def test_rejects_path_that_could_change_origin_or_embed_query(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    transport, opener, _ = _transport(monkeypatch)

    with pytest.raises(ValueError, match="absolute-path reference"):
        transport.get_json(path=path, query={"start": "0"})

    assert opener.calls == []


def test_rejects_non_string_query_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, opener, _ = _transport(monkeypatch)

    with pytest.raises(TypeError, match="string keys and values"):
        transport.get_json(
            path="/rest/api/search",
            query={"start": 0},  # type: ignore[dict-item]
        )

    assert opener.calls == []


def test_http_error_is_safe_and_contains_only_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        f"https://fixture.invalid/{PAT}",
        401,
        "Unauthorized",
        hdrs=None,
        fp=None,
    )
    transport, opener, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/content/1000", query={"expand": "x"})

    message = str(exc_info.value)
    assert "401" in message
    assert PAT not in message
    assert "fixture.invalid" not in message
    assert len(opener.calls) == 1


@pytest.mark.parametrize("method_name", ("get_json", "get_response_bytes"))
def test_oversized_decimal_retry_after_never_escapes_raw_value_error(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    headers = Message()
    headers["Retry-After"] = "9" * 5000
    failure = urllib.error.HTTPError(
        "https://fixture.invalid",
        503,
        "Service Unavailable",
        hdrs=headers,
        fp=BytesIO(b"{}"),
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    if method_name == "get_response_bytes":
        response = transport.get_response_bytes(
            path="/rest/api/content/1000/restriction/byOperation/view",
            query={},
        )
        assert response.status_code == 503
        assert response.retry_after.state is ConfluenceRetryAfterState.IGNORED
    else:
        with pytest.raises(ConfluenceHttpError) as exc_info:
            transport.get_json(path="/rest/api/content/1000", query={})
        assert exc_info.value.metadata is not None
        assert (
            exc_info.value.metadata.kind
            is ConfluenceHttpFailureKind.HTTP_STATUS
        )
        assert (
            exc_info.value.metadata.retry_after.state
            is ConfluenceRetryAfterState.IGNORED
        )


def test_network_error_does_not_disclose_reason_hostname_or_pat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.URLError(f"cannot reach fixture.invalid using {PAT}")
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    message = str(exc_info.value)
    assert message == "Confluence GET failed"
    assert PAT not in message
    assert "fixture.invalid" not in message


def test_malformed_json_fails_without_dumping_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = f"not-json {PAT} private-page-title".encode()
    transport, _, _ = _transport(monkeypatch, response=FakeResponse(body=body))

    with pytest.raises(ConfluenceHttpError, match="malformed JSON") as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    assert PAT not in str(exc_info.value)
    assert "private-page-title" not in str(exc_info.value)


def test_non_json_content_type_fails_without_dumping_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        body=b"<html>private login page</html>",
        content_type="text/html",
    )
    transport, _, _ = _transport(monkeypatch, response=response)

    with pytest.raises(ConfluenceHttpError, match="non-JSON") as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    assert "private login page" not in str(exc_info.value)


@pytest.mark.parametrize("content_type", (None, "application/problem+json"))
def test_missing_or_json_compatible_content_type_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str | None,
) -> None:
    transport, _, _ = _transport(
        monkeypatch,
        response=FakeResponse(content_type=content_type),
    )

    assert transport.get_json(
        path="/rest/api/search",
        query={"start": "0"},
    ) == {"ok": True}


def test_non_object_json_payload_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, _, _ = _transport(
        monkeypatch,
        response=FakeResponse(body=b"[]"),
    )

    with pytest.raises(ConfluenceHttpError, match="non-object"):
        transport.get_json(path="/rest/api/search", query={"start": "0"})


def test_response_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(body=b"123456789")
    transport, _, _ = _transport(
        monkeypatch,
        response=response,
        max_response_bytes=8,
    )

    with pytest.raises(ConfluenceHttpError, match="response size limit"):
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    assert response.read_limits == [9]


def test_redirect_handler_refuses_cross_origin_request() -> None:
    handler = transport_module._RefuseRedirectHandler()
    original_request = urllib.request.Request(
        "https://fixture.invalid/rest/api/search",
        headers={"Authorization": f"Bearer {PAT}"},
    )

    redirected = handler.redirect_request(
        original_request,
        None,
        302,
        "Found",
        {},
        "https://other.invalid/steal",
    )

    assert redirected is None


_RAW_BODY = (
    '{"id":"1000","title":"T\\u00e9st  ","body":'
    '{"storage":{"value":"<p>a  b</p>\\n","representation":"storage"}},'
    "\"trailing\":true}  \n"
).encode("utf-8")


def test_get_bytes_returns_exact_body_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(body=_RAW_BODY)
    transport, opener, _ = _transport(
        monkeypatch, response=response, max_response_bytes=len(_RAW_BODY)
    )

    raw = transport.get_bytes(path="/rest/api/content/1000", query={"expand": "x"})

    # Byte-for-byte: unicode escapes, double spaces, newline, key order, and the
    # trailing bytes after the closing brace are all preserved unchanged.
    assert raw == _RAW_BODY
    assert isinstance(raw, bytes)
    assert len(opener.calls) == 1
    request, _timeout = opener.calls[0]
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == f"Bearer {PAT}"
    assert request.full_url == (
        "https://fixture.invalid/confluence/rest/api/content/1000?expand=x"
    )


def test_get_bytes_does_not_parse_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_json would reject this; get_bytes must return it verbatim.
    body = b"not-json-at-all"
    transport, _, _ = _transport(monkeypatch, response=FakeResponse(body=body))

    assert transport.get_bytes(path="/rest/api/content/1000", query={}) == body


def test_get_bytes_enforces_the_response_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(body=b"123456789")
    transport, _, _ = _transport(
        monkeypatch, response=response, max_response_bytes=8
    )

    with pytest.raises(ConfluenceHttpError, match="response size limit"):
        transport.get_bytes(path="/rest/api/content/1000", query={})

    assert response.read_limits == [9]


def test_get_bytes_rejects_non_json_content_type_without_dumping_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        body=b"<html>private login page</html>", content_type="text/html"
    )
    transport, _, _ = _transport(monkeypatch, response=response)

    with pytest.raises(ConfluenceHttpError, match="non-JSON") as exc_info:
        transport.get_bytes(path="/rest/api/content/1000", query={})

    assert "private login page" not in str(exc_info.value)


def test_get_bytes_http_error_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = urllib.error.HTTPError(
        f"https://fixture.invalid/{PAT}", 401, "Unauthorized", hdrs=None, fp=None
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_bytes(path="/rest/api/content/1000", query={"expand": "x"})

    message = str(exc_info.value)
    assert "401" in message
    assert PAT not in message
    assert "fixture.invalid" not in message


def test_get_bytes_network_error_discloses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.URLError(f"cannot reach fixture.invalid using {PAT}")
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_bytes(path="/rest/api/content/1000", query={})

    message = str(exc_info.value)
    assert message == "Confluence GET failed"
    assert PAT not in message
    assert "fixture.invalid" not in message


def test_get_json_and_get_bytes_share_the_same_guarded_primitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: get_json still parses to a dict from the same bytes get_bytes
    # returns raw, proving the refactor did not change get_json behavior.
    body = b'{"id":"1000","ok":true}'
    transport, _, _ = _transport(monkeypatch, response=FakeResponse(body=body))
    assert transport.get_json(path="/rest/api/content/1000", query={}) == {
        "id": "1000",
        "ok": True,
    }

    transport2, _, _ = _transport(monkeypatch, response=FakeResponse(body=body))
    assert transport2.get_bytes(path="/rest/api/content/1000", query={}) == body


def test_status_aware_get_preserves_exact_404_status_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"<html>synthetic unavailable</html>\n"
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        404,
        "Not Found",
        hdrs=None,
        fp=BytesIO(body),
    )
    transport, opener, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 404
    assert response.body == body
    request, _ = opener.calls[0]
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == f"Bearer {PAT}"


def test_status_aware_get_preserves_empty_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        403,
        "Forbidden",
        hdrs=None,
        fp=None,
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 403
    assert response.body == b""


def test_status_aware_response_repr_does_not_disclose_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"private-synthetic-response-body"
    transport, _, _ = _transport(
        monkeypatch,
        response=FakeResponse(body=body),
    )
    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )
    assert "private-synthetic-response-body" not in repr(response)


def test_status_aware_get_does_not_require_json_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"synthetic plain body"
    transport, _, _ = _transport(
        monkeypatch,
        response=FakeResponse(body=body, status=200, content_type="text/plain"),
    )

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 200
    assert response.body == body


def test_status_aware_get_rejects_redirect_instead_of_returning_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/redirect",
        302,
        "Found",
        hdrs=None,
        fp=BytesIO(b"redirect body"),
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError, match="302"):
        transport.get_response_bytes(
            path="/rest/api/content/1000/restriction/byOperation/view",
            query={},
        )


def test_status_aware_get_enforces_response_size_limit_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        404,
        "Not Found",
        hdrs=None,
        fp=BytesIO(b"123456789"),
    )
    transport, _, _ = _transport(
        monkeypatch,
        outcome=failure,
        max_response_bytes=8,
    )

    with pytest.raises(ConfluenceHttpResponseTooLargeError):
        transport.get_response_bytes(
            path="/rest/api/content/1000/restriction/byOperation/view",
            query={},
        )


def test_status_aware_get_wraps_failure_while_reading_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingBody(BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("private synthetic socket failure")

    body = FailingBody(b"private response body")
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        404,
        "Not Found",
        hdrs=None,
        fp=body,
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_response_bytes(
            path="/rest/api/content/1000/restriction/byOperation/view",
            query={},
        )

    assert str(exc_info.value) == "Confluence GET failed"
    assert "socket" not in str(exc_info.value)
    assert body.closed


def _transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: FakeResponse | None = None,
    outcome: object | None = None,
    max_response_bytes: int = 1024,
) -> tuple[UrllibConfluenceHttpTransport, RecordingOpener, list[object]]:
    selected_outcome = outcome if outcome is not None else response or FakeResponse()
    opener = RecordingOpener(selected_outcome)
    captured_handlers: list[object] = []

    def build_opener(*handlers: object) -> RecordingOpener:
        captured_handlers.extend(handlers)
        return opener

    monkeypatch.setattr(transport_module.urllib.request, "build_opener", build_opener)
    transport = UrllibConfluenceHttpTransport(
        base_url=BASE_URL,
        personal_access_token=PAT,
        timeout_seconds=12.5,
        max_response_bytes=max_response_bytes,
    )
    return transport, opener, captured_handlers


# ---------------------------------------------------------------------------
# M7-B1: structured HTTP outcome and failure metadata
# ---------------------------------------------------------------------------


def test_response_default_retry_after_is_absent() -> None:
    response = ConfluenceHttpResponse(status_code=200, body=b"")
    assert response.retry_after.state is ConfluenceRetryAfterState.ABSENT


def test_get_json_429_carries_http_status_and_parsed_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/",
        429,
        "Too Many Requests",
        hdrs=Message(),
        fp=None,
    )
    failure.headers["Retry-After"] = "30"
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.HTTP_STATUS
    assert metadata.http_status == 429
    assert metadata.retry_after.state is ConfluenceRetryAfterState.VALID
    assert metadata.retry_after.delay_seconds == 30


def test_get_bytes_503_carries_http_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/", 503, "Unavailable", hdrs=None, fp=None
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_bytes(path="/rest/api/content/1000", query={})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.HTTP_STATUS
    assert metadata.http_status == 503


def test_terminal_400_carries_http_status_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/", 400, "Bad Request", hdrs=None, fp=None
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.HTTP_STATUS
    assert metadata.http_status == 400


def test_get_json_redirect_carries_redirect_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(status=302)
    transport, _, _ = _transport(monkeypatch, response=response)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE
    assert metadata.http_status == 302
    assert metadata.retry_after.state is ConfluenceRetryAfterState.ABSENT


def test_malformed_json_carries_malformed_json_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _, _ = _transport(
        monkeypatch, response=FakeResponse(body=b"not-json")
    )

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.MALFORMED_JSON


def test_non_object_json_carries_payload_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _, _ = _transport(monkeypatch, response=FakeResponse(body=b"[]"))

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE


def test_invalid_response_headers_carry_payload_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HeadersWithoutGet:
        pass

    response = FakeResponse()
    response.headers = HeadersWithoutGet()  # type: ignore[assignment]
    transport, _, _ = _transport(monkeypatch, response=response)

    with pytest.raises(ConfluenceHttpError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE


def test_too_large_error_carries_response_too_large_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(body=b"123456789")
    transport, _, _ = _transport(
        monkeypatch, response=response, max_response_bytes=8
    )

    with pytest.raises(ConfluenceHttpResponseTooLargeError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    metadata = exc_info.value.metadata
    assert metadata is not None
    assert metadata.kind is ConfluenceHttpFailureKind.RESPONSE_TOO_LARGE


def test_status_aware_404_preserves_body_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"<html>synthetic unavailable</html>\n"
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        404,
        "Not Found",
        hdrs=Message(),
        fp=BytesIO(body),
    )
    failure.headers["Retry-After"] = "5"
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 404
    assert response.body == body
    assert response.retry_after.state is ConfluenceRetryAfterState.VALID
    assert response.retry_after.delay_seconds == 5


def test_status_aware_500_preserves_body_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"secret"
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        500,
        "Server Error",
        hdrs=None,
        fp=BytesIO(body),
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 500
    assert response.body == body
    assert response.retry_after.state is ConfluenceRetryAfterState.ABSENT


def test_status_aware_429_returns_observation_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted",
        429,
        "Too Many Requests",
        hdrs=Message(),
        fp=BytesIO(b"rate limited"),
    )
    failure.headers["Retry-After"] = "10"
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.status_code == 429
    assert response.body == b"rate limited"
    assert response.retry_after.state is ConfluenceRetryAfterState.VALID
    assert response.retry_after.delay_seconds == 10


def test_status_aware_http_error_hdrs_none_yields_absent_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = urllib.error.HTTPError(
        "https://fixture.invalid/restricted", 403, "Forbidden", hdrs=None, fp=None
    )
    transport, _, _ = _transport(monkeypatch, outcome=failure)

    response = transport.get_response_bytes(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert response.retry_after.state is ConfluenceRetryAfterState.ABSENT


def test_error_repr_does_not_disclose_metadata_values() -> None:
    from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
        ConfluenceHttpFailureMetadata,
        confluence_retry_after_absent,
    )

    error = ConfluenceHttpError(
        "Confluence GET returned HTTP status 429",
        metadata=ConfluenceHttpFailureMetadata(
            kind=ConfluenceHttpFailureKind.HTTP_STATUS,
            http_status=429,
            retry_after=confluence_retry_after_absent(),
        ),
    )
    rendered = repr(error)
    assert "HTTP_STATUS" not in rendered
    assert "ConfluenceHttpFailureMetadata" not in rendered


# ---------------------------------------------------------------------------
# Caller-validation regressions (must remain TypeError/ValueError, zero calls)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    ("get_json", "get_bytes", "get_response_bytes"),
)
def test_invalid_path_stays_value_error_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    transport, opener, _ = _transport(monkeypatch)
    method = getattr(transport, method_name)

    with pytest.raises(ValueError, match="absolute-path reference"):
        method(path="rest/api/search", query={"start": "0"})

    assert opener.calls == []


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "/rest/api/\r\nInjected: yes",
        "/rest/api/\x00",
        "/rest/api/../admin",
        "/rest/api/%2e%2e/admin",
        "/rest\\api\\admin",
    ),
)
def test_unsafe_path_is_rejected_before_outbound_call(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_path: str,
) -> None:
    transport, opener, _ = _transport(monkeypatch)

    with pytest.raises(ValueError, match="safe absolute-path"):
        transport.get_json(path=unsafe_path, query={})

    assert opener.calls == []


@pytest.mark.parametrize(
    "method_name",
    ("get_json", "get_bytes", "get_response_bytes"),
)
def test_non_mapping_query_stays_type_error_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    transport, opener, _ = _transport(monkeypatch)
    method = getattr(transport, method_name)

    with pytest.raises(TypeError, match="mapping of strings"):
        method(path="/rest/api/search", query=["start", "0"])  # type: ignore[arg-type]

    assert opener.calls == []


@pytest.mark.parametrize(
    "method_name",
    ("get_json", "get_bytes", "get_response_bytes"),
)
def test_non_string_query_entry_stays_type_error_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    transport, opener, _ = _transport(monkeypatch)
    method = getattr(transport, method_name)

    with pytest.raises(TypeError, match="string keys and values"):
        method(path="/rest/api/search", query={"start": 0})  # type: ignore[dict-item]

    assert opener.calls == []
