from __future__ import annotations

import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest

from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceHttpError,
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
