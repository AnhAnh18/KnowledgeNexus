from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from knowledgenexus.foundation.cli.capture_confluence_mini_corpus import (
    _CaptureError,
    _capture_pages,
    _discover_page_ids,
    _load_page_ids,
    _parse_args,
    _publish_selection,
    main,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
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


class _Inventory:
    def __init__(self, pages: tuple[ConfluencePageMetadata, ...]) -> None:
        self.pages = pages

    def iter_page_metadata(
        self, *, space_key: str, root_page_id: str, page_size: int
    ):
        assert space_key == "SPACE"
        assert root_page_id == "1000"
        assert page_size == 25
        return iter(self.pages)


def _metadata(
    page_id: str,
    *,
    parent_page_id: str | None,
    ancestor_page_ids: tuple[str, ...],
) -> ConfluencePageMetadata:
    return ConfluencePageMetadata(
        page_id=page_id,
        title=f"Page {page_id}",
        space_key="SPACE",
        parent_page_id=parent_page_id,
        ancestor_page_ids=ancestor_page_ids,
        ancestor_titles=tuple(f"Page {value}" for value in ancestor_page_ids),
        updated_at="2026-08-05T00:00:00Z",
        source_version="1",
        labels=(),
        attachment_count=None,
    )


def test_page_id_input_requires_ten_to_twenty_unique_ids(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text(json.dumps([str(1000 + index) for index in range(10)]), encoding="utf-8")
    assert _load_page_ids(path) == tuple(str(1000 + index) for index in range(10))

    path.write_text(json.dumps(["1000"] * 10), encoding="utf-8")
    with pytest.raises(Exception):
        _load_page_ids(path)

    path.write_text(
        json.dumps([str(1000 + index) for index in range(21)]),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        _load_page_ids(path)


def test_root_inventory_discovers_exact_bounded_tree_with_root_first() -> None:
    root = _metadata("1000", parent_page_id=None, ancestor_page_ids=())
    children = tuple(
        _metadata(
            str(1000 + index),
            parent_page_id="1000",
            ancestor_page_ids=("1000",),
        )
        for index in range(1, 10)
    )

    page_ids = _discover_page_ids(
        inventory_port=_Inventory((children[4], root, *children[:4], *children[5:])),
        root_page_id="1000",
        space_key="SPACE",
        expected_page_count=10,
        page_size=25,
    )

    assert page_ids == ("1000", *(str(1000 + index) for index in range(1, 10)))


def test_root_inventory_count_mismatch_fails_before_body_capture() -> None:
    root = _metadata("1000", parent_page_id=None, ancestor_page_ids=())
    children = tuple(
        _metadata(
            str(1000 + index),
            parent_page_id="1000",
            ancestor_page_ids=("1000",),
        )
        for index in range(1, 9)
    )

    with pytest.raises(_CaptureError) as caught:
        _discover_page_ids(
            inventory_port=_Inventory((root, *children)),
            root_page_id="1000",
            space_key="SPACE",
            expected_page_count=10,
            page_size=25,
        )

    assert caught.value.category == "inventory_scope"
    assert caught.value.published_pages == 0


def test_cli_selection_modes_are_mutually_exclusive_and_root_mode_is_explicit() -> None:
    common = [
        "--data-root",
        "C:/external/raw",
        "--selection-out",
        "C:/external/selection.json",
        "--run-id",
        str(RUN_ID),
    ]
    root_args = _parse_args(
        [
            *common,
            "--root-page-id",
            "1000",
            "--space-key",
            "SPACE",
            "--expected-page-count",
            "10",
        ]
    )
    assert root_args.root_page_id == "1000"
    assert root_args.page_ids_path is None

    with pytest.raises(Exception):
        _parse_args(
            [
                *common,
                "--root-page-id",
                "1000",
                "--page-ids-path",
                "C:/external/ids.json",
            ]
        )

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


def test_discovered_capture_rejects_body_that_moved_to_another_space() -> None:
    class WrongSpaceFetcher(_Fetcher):
        def fetch_page_response_raw(self, *, page_id: str) -> ConfluenceHttpResponse:
            body = json.loads(_raw(page_id).decode("utf-8"))
            body["space"]["key"] = "OTHER"
            return ConfluenceHttpResponse(
                status_code=200,
                body=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            )

    store = _Store()
    with pytest.raises(_CaptureError) as caught:
        _capture_pages(
            run_id=RUN_ID,
            page_ids=tuple(str(1000 + index) for index in range(10)),
            page_fetcher=WrongSpaceFetcher(),
            page_mapper=_Mapper(),
            generation_store=store,
            expected_space_key="SPACE",
        )

    assert caught.value.category == "page_mapping"
    assert caught.value.published_pages == 0
    assert store.envelopes == []


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
