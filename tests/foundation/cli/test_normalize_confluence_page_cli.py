from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli import normalize_confluence_page as cli

PAGE_ID = "1000"
CRAWLED_AT = "2026-07-21T02:03:04Z"


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6C tests must not open a network connection")

    monkeypatch.setattr(urllib.request, "build_opener", explode)
    monkeypatch.setattr(urllib.request, "urlopen", explode)


def _write_page(raw_root: Path, *, xhtml: str = "<p>Secret body</p>") -> Path:
    target = raw_root / "confluence" / "pages" / f"{PAGE_ID}.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "id": PAGE_ID,
                "type": "page",
                "title": "Secret title",
                "space": {"key": "SECRETSPACE"},
                "version": {"number": 3, "when": "2026-07-20T01:02:03Z"},
                "body": {
                    "storage": {
                        "value": xhtml,
                        "representation": "storage",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return target


def _argv(raw_root: Path, **over: str) -> list[str]:
    return [
        "--page-id",
        over.get("page_id", PAGE_ID),
        "--raw-root",
        str(raw_root),
        "--crawled-at",
        over.get("crawled_at", CRAWLED_AT),
    ]


def test_offline_cli_composes_production_components_and_persists_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_page = _write_page(
        tmp_path,
        xhtml=(
            '<ac:structured-macro ac:name="toc"/>'
            '<ac:structured-macro ac:name="unknown"><ac:rich-text-body>'
            "<p>Secret body</p></ac:rich-text-body></ac:structured-macro>"
        ),
    )
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    assert cli.main(_argv(tmp_path)) == 0

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert after == before
    assert raw_page.is_file()
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "canonical_document_valid": True,
        "handled_macro_count": 1,
        "media_placeholder_count": 0,
        "status": "success",
        "toc_dropped": 1,
        "unhandled_macro_count": 1,
        "unsupported_element_count": 0,
        "warning_count": 1,
    }


def test_success_output_contains_no_source_identity_content_path_url_or_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_page(tmp_path)
    assert cli.main(_argv(tmp_path)) == 0
    output = capsys.readouterr().out
    for forbidden in (
        PAGE_ID,
        "Secret title",
        "Secret body",
        "SECRETSPACE",
        str(tmp_path),
        "confluence/pages",
        "http://",
        "https://",
        "content_hash",
    ):
        assert forbidden not in output


def test_missing_raw_page_fails_with_sanitized_category(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(_argv(tmp_path)) == cli.EXIT_CODES["raw_page_input"]
    error = json.loads(capsys.readouterr().err)
    assert error == {"category": "raw_page_input", "status": "failed"}
    assert PAGE_ID not in str(error)


def test_malformed_xhtml_failure_does_not_leak_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_page(tmp_path, xhtml="<p>REVIEW_SENTINEL_SECRET")
    assert cli.main(_argv(tmp_path)) == cli.EXIT_CODES["storage_xhtml"]
    output = capsys.readouterr()
    assert json.loads(output.err)["category"] == "storage_xhtml"
    assert "REVIEW_SENTINEL_SECRET" not in output.err
    assert "REVIEW_SENTINEL_SECRET" not in output.out


def test_argument_error_never_echoes_page_or_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "REVIEW_SENTINEL_SECRET"
    assert cli.main([*_argv(tmp_path), "--bogus", secret]) == 2
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert str(tmp_path) not in captured.err


def test_cli_has_no_credential_or_network_option() -> None:
    parser_error = cli.main(
        [
            "--page-id",
            PAGE_ID,
            "--raw-root",
            "data/raw",
            "--crawled-at",
            CRAWLED_AT,
            "--pat",
            "SECRET",
        ]
    )
    assert parser_error == 2
