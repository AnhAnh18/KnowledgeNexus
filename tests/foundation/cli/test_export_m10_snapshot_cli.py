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


def test_media_policy_maps_to_typed_contract():
    assert cli._media_policy("disabled").include_attachments is False
    assert cli._media_policy("best-effort").allow_download is False
    assert cli._media_policy("required").allow_download is True


def test_processed_media_is_projected_to_relation_model():
    processed = {
        "schema_version": "1.0", "media_id": "confluence:attachment:2000",
        "parent_document_id": "confluence:page:1000", "source_system": "confluence",
        "filename": "diagram.drawio", "mime_type": "application/xml", "size_bytes": 4,
        "download_status": "downloaded", "processing_status": "parsed", "relevance": "high",
        "extracted_text": "node", "summary": None, "confidence": 1.0,
        "raw_uri": "raw://confluence/attachments/2000/" + "a" * 64,
        "content_hash": "a" * 64, "source_version": "1", "updated_at": None,
        "crawled_at": "2026-08-08T00:00:00Z",
    }
    projected = cli._relation_media_asset(processed)
    from knowledgenexus.foundation.domain.models.media_materialization import MediaMaterializationResult
    result = MediaMaterializationResult(assets=(projected,), relation_intents=())
    assert result.assets[0]["processing_status"] == "not_processed"


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
