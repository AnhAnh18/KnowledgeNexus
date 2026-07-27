from __future__ import annotations

import pytest

from knowledgenexus.presentation.cli.agent.formatters import (
    format_documents_text,
    format_health_text,
    format_search_text,
    format_stats_text,
)
from knowledgenexus.presentation.cli.agent.__main__ import build_parser, main
from knowledgenexus.presentation.cli.agent.http import CliError


def test_format_search_text_includes_title_and_score():
    text = format_search_text(
        "table layout",
        {
            "total": 1,
            "results": [
                {
                    "score": 0.89,
                    "content": "TableLayout renders tables",
                    "citation": {
                        "title": "Table Doc",
                        "source_type": "markdown",
                        "source_id": "doc_1",
                        "file_path": "docs/Table.md",
                        "line_start": 10,
                        "line_end": 20,
                    },
                }
            ],
        },
    )
    assert 'Found 1 result(s) for "table layout"' in text
    assert "Title: Table Doc" in text
    assert "score: 0.8900" in text
    assert "docs/Table.md:10-20" in text


def test_format_documents_text():
    text = format_documents_text(
        {
            "total": 1,
            "offset": 0,
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Table Doc",
                    "source_type": "markdown",
                    "source_id": "doc_1",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        }
    )
    assert "Documents: 1 total" in text
    assert "Table Doc" in text


def test_format_stats_text():
    text = format_stats_text(
        {
            "total_documents": 42,
            "total_chunks": 1500,
            "collection_name": "knowledgenexus",
        }
    )
    assert "Store Statistics" in text
    assert "Total Documents: 42" in text
    assert "Total Chunks: 1500" in text
    assert "Collection Name: knowledgenexus" in text


def test_format_stats_text_empty():
    text = format_stats_text({})
    assert "Store Statistics" in text


def test_format_health_text():
    text = format_health_text(
        {
            "status": "healthy",
            "version": "0.1.0",
            "qdrant_connected": True,
        }
    )
    assert "API Status: healthy" in text
    assert "Version: 0.1.0" in text
    assert "Qdrant Connected: True" in text


def test_format_health_text_unknown_status():
    text = format_health_text({})
    assert "API Status: unknown" in text


def test_umbrella_parser_requires_command():
    parser = build_parser()
    assert parser.parse_args(["search", "hello"]).command == "search"
    assert parser.parse_args(["health"]).command == "health"


def test_umbrella_parser_has_all_subcommands():
    parser = build_parser()
    # search requires a positional query argument
    assert parser.parse_args(["search", "query"]).command == "search"
    # the rest have no required positionals
    for cmd in ("list-docs", "stats", "health"):
        assert parser.parse_args([cmd]).command == cmd


def test_search_top_k_rejects_over_50():
    """--top-k must reject values > 50 (matching API validation le=50)."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["search", "query", "--top-k", "51"])


def test_search_top_k_accepts_50():
    """--top-k=50 should be the maximum accepted value."""
    parser = build_parser()
    args = parser.parse_args(["search", "query", "--top-k", "50"])
    assert args.top_k == 50


def test_search_top_k_rejects_zero():
    """--top-k=0 should be rejected (min is 1)."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["search", "query", "--top-k", "0"])


def test_main_returns_1_when_no_command(capsys):
    """Running `kn` with no subcommand should print help and return 1."""
    ret = main([])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Available commands" in captured.out or "usage" in captured.out.lower()


def test_main_catches_cli_error(monkeypatch, capsys):
    """main() should catch CliError and return 1 instead of crashing."""
    from knowledgenexus.presentation.cli.agent import health

    def fake_run():
        raise CliError("Connection Error: refused")

    monkeypatch.setattr(health, "run", fake_run)
    ret = main(["health"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Connection Error" in captured.err
