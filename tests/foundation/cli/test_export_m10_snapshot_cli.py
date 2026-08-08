from __future__ import annotations

import json

from knowledgenexus.foundation.cli import export_m10_snapshot as cli
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class _Adapter:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def collect(self, request):
        self.calls += 1
        return self.value


def test_cli_rejects_missing_injected_boundary_without_output(capsys):
    assert cli.main([]) == cli.EXIT_INVALID_REQUEST
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"category": "invalid_request", "status": "failed"}


def test_cli_success_is_sanitized_and_offline(tmp_path, capsys):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    assert cli.main(request=request, confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(git)) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert payload["network_used"] is False
    assert payload["credentials_used"] is False
    assert captured.err == ""


def test_cli_unknown_argument_is_stable_and_silent(capsys):
    assert cli.main(["--unknown-sensitive-path=C:/secret"]) == cli.EXIT_CONFIGURATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "secret" not in captured.err


def test_cli_help_returns_success(capsys):
    assert cli.main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "export-m10-snapshot" in captured.out
    assert captured.err == ""


def test_cli_sanitizes_non_integer_system_exit(monkeypatch, capsys):
    def raise_secret(_argv):
        raise SystemExit("secret payload")

    monkeypatch.setattr(cli, "_parse_args", raise_secret)
    assert cli.main([]) == cli.EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"category": "unexpected", "status": "failed"}
    assert "secret" not in captured.err


def test_cli_rejects_malformed_success_result_without_leaking(monkeypatch, tmp_path, capsys):
    request = _request(tmp_path)
    confluence, git = _handoffs()

    monkeypatch.setattr(cli, "run", lambda **_: object())
    assert cli.main(request=request, confluence_adapter=_Adapter(confluence), git_adapter=_Adapter(git)) == cli.EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"category": "unexpected", "status": "failed"}
