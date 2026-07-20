from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import collect_confluence_page_observations as cli
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceHttpResponse,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)

PAGE_ID = "1000"
BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"
SECRET_FILENAME = "private-synthetic-file.pdf"
SECRET_PRINCIPAL = "private-synthetic-user"


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("offline tests must never open a network connection")

    monkeypatch.setattr(transport_module.urllib.request, "build_opener", explode)
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", explode)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.BASE_URL_ENV, BASE_URL)
    monkeypatch.setenv(cli.PAT_ENV, PAT)


class FakeTransport:
    last: FakeTransport | None = None

    def __init__(self, *, base_url: str, personal_access_token: str, **kwargs: object):
        self.base_url = base_url
        self.pat = personal_access_token
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        FakeTransport.last = self

    def get_response_bytes(
        self, *, path: str, query: Mapping[str, str]
    ) -> ConfluenceHttpResponse:
        self.calls.append(("restriction", path, dict(query)))
        body = json.dumps(
            {
                "operation": "view",
                "restrictions": {
                    "user": {"results": [{"username": SECRET_PRINCIPAL}]},
                    "group": {"results": []},
                },
            }
        ).encode()
        return ConfluenceHttpResponse(status_code=200, body=body)

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.calls.append(("attachment", path, dict(query)))
        return json.dumps(
            {
                "results": [
                    {"id": "2000", "type": "attachment", "title": SECRET_FILENAME}
                ],
                "_links": {},
            }
        ).encode()


def _install(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTransport.last = None
    monkeypatch.setattr(cli, "UrllibConfluenceHttpTransport", FakeTransport)


def _write_page(root: Path) -> None:
    target = root / "confluence" / "pages" / f"{PAGE_ID}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        json.dumps({"id": PAGE_ID, "ancestors": [{"id": "900"}]}).encode()
    )


def _argv(root: Path) -> list[str]:
    return [
        "--page-id",
        PAGE_ID,
        "--raw-root",
        str(root),
        "--attachment-page-size",
        "2",
        "--max-attachment-pages",
        "10",
    ]


def test_success_composes_production_adapters_and_prints_only_booleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_page(tmp_path)
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 0

    captured = capsys.readouterr()
    assert set(captured.out.split()) == {f"{name}=true" for name in cli._SUCCESS_CHECKS}
    assert captured.err == ""
    transport = FakeTransport.last
    assert transport is not None
    assert [kind for kind, _path, _query in transport.calls] == [
        "restriction",
        "restriction",
        "attachment",
    ]
    for sensitive in (
        PAT,
        BASE_URL,
        PAGE_ID,
        "900",
        "2000",
        SECRET_FILENAME,
        SECRET_PRINCIPAL,
    ):
        assert sensitive not in captured.out
        assert sensitive not in captured.err


def test_missing_page_fails_before_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 4

    assert json.loads(capsys.readouterr().err)["category"] == "raw_page_input"
    assert FakeTransport.last is not None
    assert FakeTransport.last.calls == []


def test_pat_cannot_be_supplied_on_command_line_without_echo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch)
    value = "REVIEW_SENTINEL_SECRET"

    assert cli.main([*_argv(tmp_path), "--pat", value]) == 2

    captured = capsys.readouterr()
    assert value not in captured.out
    assert value not in captured.err


@pytest.mark.parametrize("missing", [cli.BASE_URL_ENV, cli.PAT_ENV])
def test_missing_environment_credential_is_sanitized_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    _write_page(tmp_path)
    _install(monkeypatch)
    monkeypatch.delenv(missing)

    assert cli.main(_argv(tmp_path)) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.err)["category"] == "configuration"
    assert PAT not in captured.err
    assert BASE_URL not in captured.err
