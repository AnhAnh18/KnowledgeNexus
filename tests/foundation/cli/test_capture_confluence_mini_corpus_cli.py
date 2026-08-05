from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli.capture_confluence_mini_corpus import (
    _CaptureError,
    _capture_pages,
    _load_page_ids,
    _publish_selection,
    main,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.infrastructure.confluence import ConfluenceHttpResponse


RUN_ID = CrawlRunId("12345678-1234-4234-8234-123456789abc")


def test_help_exits_successfully_without_failure_json(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])

    captured = capsys.readouterr()
    assert caught.value.code == 0
    assert "usage: capture-confluence-mini-corpus" in captured.out
    assert captured.err == ""


def _raw(page_id: str, version: int = 7) -> bytes:
    return json.dumps(
        {
            "id": page_id,
            "type": "page",
            "title": "Fixture",
            "space": {"key": "SPACE"},
            "version": {"number": version, "when": "2026-08-05T00:00:00Z"},
            "body": {
                "storage": {
                    "value": "<p>Fixture</p>",
                    "representation": "storage",
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


class _Fetcher:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at = fail_at

    def fetch_page_response_raw(self, *, page_id: str) -> ConfluenceHttpResponse:
        self.calls.append(page_id)
        if self.fail_at == len(self.calls):
            raise OSError("sensitive fixture detail")
        return ConfluenceHttpResponse(status_code=200, body=_raw(page_id))


class _Mapper:
    def map_page(self, *, raw_bytes: bytes, expected_page_id: str):
        from knowledgenexus.foundation.infrastructure.processors import (
            ConfluenceDataCenterRawPageMapper,
        )

        return ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=raw_bytes,
            expected_page_id=expected_page_id,
        )


class _Store:
    def __init__(self) -> None:
        self.envelopes: list[ConfluenceRawPageEnvelope] = []

    def publish_page(self, *, envelope: ConfluenceRawPageEnvelope):
        self.envelopes.append(envelope)
        return SimpleNamespace(outcome=ConfluenceRawPagePublicationOutcome.PUBLISHED)


def test_page_id_input_requires_ten_to_twenty_unique_ids(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text(json.dumps([str(1000 + index) for index in range(10)]), encoding="utf-8")
    assert _load_page_ids(path) == tuple(str(1000 + index) for index in range(10))

    path.write_text(json.dumps(["1000"] * 10), encoding="utf-8")
    with pytest.raises(Exception):
        _load_page_ids(path)

    path.write_text(json.dumps([str(1000 + index) for index in range(21)]), encoding="utf-8")
    with pytest.raises(Exception):
        _load_page_ids(path)


def test_capture_preserves_exact_bytes_and_builds_m8_selection() -> None:
    page_ids = tuple(str(1000 + index) for index in range(10))
    fetcher = _Fetcher()
    store = _Store()
    selection = _capture_pages(
        run_id=RUN_ID,
        page_ids=page_ids,
        page_fetcher=fetcher,
        page_mapper=_Mapper(),
        generation_store=store,
    )

    assert fetcher.calls == list(page_ids)
    assert len(store.envelopes) == len(selection) == 10
    for page_id, envelope, entry in zip(page_ids, store.envelopes, selection):
        assert envelope.run_id == envelope.generation_id == RUN_ID
        assert envelope.page_id == page_id
        assert envelope.source_version == "7"
        assert envelope.http_status == 200
        assert envelope.body_bytes == _raw(page_id)
        assert entry["page_id"] == page_id
        assert entry["expected_source_version"] == "7"
        assert entry["crawled_at"].endswith("Z")


def test_capture_stops_after_first_failure_and_reports_committed_count() -> None:
    fetcher = _Fetcher(fail_at=3)
    store = _Store()
    with pytest.raises(_CaptureError) as caught:
        _capture_pages(
            run_id=RUN_ID,
            page_ids=tuple(str(1000 + index) for index in range(10)),
            page_fetcher=fetcher,
            page_mapper=_Mapper(),
            generation_store=store,
        )
    assert caught.value.category == "page_fetch"
    assert caught.value.published_pages == 2
    assert len(fetcher.calls) == 3
    assert len(store.envelopes) == 2


def test_selection_publication_is_atomic_and_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "selection.json"
    selection = tuple(
        {
            "page_id": str(1000 + index),
            "crawled_at": "2026-08-05T00:00:00.000Z",
            "expected_source_version": "1",
        }
        for index in range(10)
    )
    _publish_selection(target, selection)
    assert json.loads(target.read_text(encoding="utf-8")) == list(selection)
    original = target.read_bytes()
    with pytest.raises(_CaptureError):
        _publish_selection(target, selection)
    assert target.read_bytes() == original
    assert not tuple(tmp_path.glob(".m8ac-selection-*.tmp"))
