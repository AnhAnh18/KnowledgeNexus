from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
    ConfluenceRawPageStore,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


def test_m6a_raw_artifact_to_m6c_canonical_document_is_offline_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("the M6C integration path must remain offline")

    monkeypatch.setattr(urllib.request, "build_opener", explode)
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    page_id = "1000"
    raw_bytes = json.dumps(
        {
            "id": page_id,
            "type": "page",
            "title": "Fixture Foundation",
            "space": {"key": "SPACE"},
            "version": {"number": 9, "when": "2026-07-20T01:02:03Z"},
            "body": {
                "storage": {
                    "value": (
                        "<h1>Design</h1><p>Cafe\u0301</p>"
                        '<ac:structured-macro ac:name="note">'
                        "<ac:rich-text-body><p>Review</p></ac:rich-text-body>"
                        "</ac:structured-macro>"
                    ),
                    "representation": "storage",
                }
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    artifact = ConfluenceRawPageStore(raw_root=tmp_path).write(
        page_id=page_id,
        raw_bytes=raw_bytes,
    )
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    use_case = NormalizeConfluencePage(
        raw_page_reader=ConfluencePageObservationStore(raw_root=tmp_path),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    )

    first = use_case.execute(
        page_id=page_id,
        crawled_at="2026-07-21T02:03:04Z",
    )
    second = use_case.execute(
        page_id=page_id,
        crawled_at="2026-07-21T02:03:04Z",
    )

    assert artifact.path.read_bytes() == raw_bytes
    assert first == second
    assert first.normalized_body_text == "# Design\n\nCafé\n\n> **Note:**\n> Review"
    FoundationSchemaValidator().validate_record(
        "CanonicalDocument",
        first.canonical_document,
    )
    assert first.canonical_document["content_hash"] == second.canonical_document[
        "content_hash"
    ]
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before
