from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import fetch_raw_confluence_page as cli
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)

PAGE_ID = "1000"
BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"
RAW = '{"id":"1000","title":"Secret Title","body":{"storage":{"value":"<p>x</p>"}}}'.encode()


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("the CLI must not open a network connection in tests")

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
        self.personal_access_token = personal_access_token
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        FakeTransport.last = self

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.calls.append({"path": path, "query": dict(query)})
        return RAW


def _install(monkeypatch: pytest.MonkeyPatch, transport_cls: type = FakeTransport) -> None:
    FakeTransport.last = None
    monkeypatch.setattr(cli, "UrllibConfluenceHttpTransport", transport_cls)


def _argv(raw_root: Path, **over: object) -> list[str]:
    argv = ["--page-id", str(over.get("page_id", PAGE_ID)), "--raw-root", str(raw_root)]
    return argv


def test_success_prints_only_sanitized_booleans_and_writes_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 0

    out = capsys.readouterr().out
    assert set(out.split()) == {f"{c}=true" for c in cli._SUCCESS_CHECKS}
    # The artifact exists with the exact bytes; the CLI never printed it.
    artifact = tmp_path / "confluence" / "pages" / "1000.json"
    assert artifact.read_bytes() == RAW
    assert PAGE_ID not in out
    assert "Secret Title" not in out
    assert "1000.json" not in out


def test_composes_production_page_adapter_and_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch)

    assert cli.main(_argv(tmp_path)) == 0

    transport = FakeTransport.last
    assert transport is not None
    assert transport.base_url == BASE_URL
    assert transport.personal_access_token == PAT
    # Exact confirmed M6-0 page request, produced by the production adapter.
    assert transport.calls == [
        {
            "path": "/rest/api/content/1000",
            "query": {"expand": "body.storage,space,version,ancestors,metadata.labels"},
        }
    ]


def test_persisted_hash_matches_exact_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch)
    assert cli.main(_argv(tmp_path)) == 0
    artifact = tmp_path / "confluence" / "pages" / "1000.json"
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == hashlib.sha256(
        RAW
    ).hexdigest()


@pytest.mark.parametrize("missing", [cli.BASE_URL_ENV, cli.PAT_ENV])
def test_missing_credential_env_fails_as_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    _install(monkeypatch)
    monkeypatch.delenv(missing)

    assert cli.main(_argv(tmp_path)) == 2

    assert json.loads(capsys.readouterr().err)["category"] == "configuration"
    assert not (tmp_path / "confluence").exists()


def test_pat_cannot_be_supplied_on_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch)

    assert cli.main([*_argv(tmp_path), "--pat", "REVIEW_SENTINEL_SECRET"]) == 2

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert "REVIEW_SENTINEL_SECRET" not in stream


def test_invalid_cli_error_never_echoes_page_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch)

    assert cli.main([*_argv(tmp_path), "--bogus", "7777777777"]) == 2

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert "7777777777" not in stream


def test_http_failure_is_sanitized_and_writes_no_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledgenexus.foundation.infrastructure.confluence import ConfluenceHttpError

    class Failing(FakeTransport):
        def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
            raise ConfluenceHttpError(
                f"Confluence GET to {BASE_URL} with {PAT} returned HTTP status 401"
            )

    _install(monkeypatch, Failing)

    assert cli.main(_argv(tmp_path)) == 4

    captured = capsys.readouterr()
    assert json.loads(captured.err)["category"] == "http"
    for stream in (captured.out, captured.err):
        assert PAT not in stream
        assert BASE_URL not in stream
        assert "fixture.invalid" not in stream
    assert not (tmp_path / "confluence").exists()


def test_identity_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Wrong(FakeTransport):
        def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
            return b'{"id":"9999"}'

    _install(monkeypatch, Wrong)

    assert cli.main(_argv(tmp_path)) == 7
    assert json.loads(capsys.readouterr().err)["category"] == "identity_mismatch"
    assert not (tmp_path / "confluence").exists()


def test_injected_credentials_never_appear_in_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch)
    assert cli.main(_argv(tmp_path)) == 0
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert PAT not in stream
        assert "fixture.invalid" not in stream
