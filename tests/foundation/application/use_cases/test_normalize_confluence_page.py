from __future__ import annotations

import hashlib
import json

import pytest

from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    CATEGORY_INVALID_PAGE_ID,
    CATEGORY_PAGE_PAYLOAD,
    CATEGORY_RAW_PAGE_INPUT,
    CATEGORY_STORAGE_XHTML,
    CATEGORY_TIMESTAMP,
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)

PAGE_ID = "1000"
CRAWLED_AT = "2026-07-21T02:03:04Z"


def _raw(*, xhtml: str = "<h2>Overview</h2><p>Body</p>", **over: object) -> bytes:
    payload: dict[str, object] = {
        "id": PAGE_ID,
        "type": "page",
        "title": "Fixture Foundation",
        "space": {"key": "SPACE"},
        "version": {"number": 7, "when": "2026-07-20T01:02:03Z"},
        "body": {"storage": {"value": xhtml, "representation": "storage"}},
    }
    payload.update(over)
    return json.dumps(payload).encode()


class Reader:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.calls: list[str] = []

    def read_page(self, *, page_id: str) -> bytes:
        self.calls.append(page_id)
        return self.raw


def _use_case(raw: bytes) -> NormalizeConfluencePage:
    return NormalizeConfluencePage(
        raw_page_reader=Reader(raw),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    )


def test_builds_schema_valid_canonical_document_with_expected_mapping() -> None:
    result = _use_case(_raw()).execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)
    document = result.canonical_document

    FoundationSchemaValidator().validate_record("CanonicalDocument", document)
    assert document["document_id"] == "confluence:page:1000"
    assert document["source_system"] == "confluence"
    assert document["source_type"] == "wiki_page"
    assert document["title"] == "Fixture Foundation"
    assert document["space_key"] == "SPACE"
    assert document["page_id"] == PAGE_ID
    assert document["source_version"] == "7"
    assert document["updated_at"] == "2026-07-20T01:02:03Z"
    assert document["crawled_at"] == CRAWLED_AT
    assert document["acl_id"] == "acl:confluence:page:1000"
    assert document["jira_keys"] == []
    assert document["relation_ids"] == []
    assert document["metadata"] == {}


def test_content_hash_covers_exact_final_normalized_body() -> None:
    result = _use_case(_raw(xhtml="<p>Cafe\u0301</p>")).execute(
        page_id=PAGE_ID,
        crawled_at=CRAWLED_AT,
    )
    assert result.normalized_body_text == "Café"
    assert result.canonical_document["content_hash"] == hashlib.sha256(
        "Café".encode("utf-8")
    ).hexdigest()


def test_same_explicit_inputs_are_byte_identical() -> None:
    first = _use_case(_raw()).execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)
    second = _use_case(_raw()).execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)

    def encode(result: object) -> bytes:
        return json.dumps(
            {
                "text": result.normalized_body_text,
                "document": result.canonical_document,
                "counters": result.counters,
                "warnings": result.warnings,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    assert encode(first) == encode(second)


def test_result_contains_no_downstream_records_or_unknown_document_fields() -> None:
    result = _use_case(_raw()).execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)
    assert not hasattr(result, "chunks")
    assert not hasattr(result, "acl_records")
    assert not hasattr(result, "media_assets")
    assert not hasattr(result, "relations")
    assert "body_text" not in result.canonical_document
    assert "raw_uri" not in result.canonical_document
    assert "parent_ids" not in result.canonical_document
    assert "labels" not in result.canonical_document


@pytest.mark.parametrize("page_id", ["", "abc", "-1"])
def test_invalid_page_identity_is_categorized(page_id: str) -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _use_case(_raw()).execute(page_id=page_id, crawled_at=CRAWLED_AT)
    assert caught.value.category == CATEGORY_INVALID_PAGE_ID


def test_reader_failure_is_categorized_without_disclosure() -> None:
    class FailingReader:
        def read_page(self, *, page_id: str) -> bytes:
            raise RawPageReadError("SECRET path and page")

    use_case = NormalizeConfluencePage(
        raw_page_reader=FailingReader(),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
    )
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        use_case.execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)
    assert caught.value.category == CATEGORY_RAW_PAGE_INPUT
    assert "SECRET" not in str(caught.value)


def test_payload_failure_is_categorized_without_disclosure() -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _use_case(b'{"title":"SECRET"}').execute(
            page_id=PAGE_ID,
            crawled_at=CRAWLED_AT,
        )
    assert caught.value.category == CATEGORY_PAGE_PAYLOAD
    assert "SECRET" not in str(caught.value)


def test_xhtml_failure_is_categorized_without_disclosure() -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _use_case(_raw(xhtml="<p>SECRET")).execute(
            page_id=PAGE_ID,
            crawled_at=CRAWLED_AT,
        )
    assert caught.value.category == CATEGORY_STORAGE_XHTML
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    "crawled_at",
    [
        "",
        "2026-07-21",
        "2026-13-40T25:61:61Z",
        "2026-07-21T01:02:03",
        "2026-07-21T01:02:03+00:60",
    ],
)
def test_crawled_at_must_be_explicit_valid_rfc3339(crawled_at: str) -> None:
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _use_case(_raw()).execute(page_id=PAGE_ID, crawled_at=crawled_at)
    assert caught.value.category == CATEGORY_TIMESTAMP


def test_invalid_source_updated_at_fails_before_building_record() -> None:
    raw = _raw(version={"number": 7, "when": "not-a-date"})
    with pytest.raises(ConfluencePageNormalizationError) as caught:
        _use_case(raw).execute(page_id=PAGE_ID, crawled_at=CRAWLED_AT)
    assert caught.value.category == CATEGORY_TIMESTAMP


def test_result_repr_does_not_disclose_content_or_identity() -> None:
    result = _use_case(_raw(xhtml="<p>REVIEW_SENTINEL_SECRET</p>")).execute(
        page_id=PAGE_ID,
        crawled_at=CRAWLED_AT,
    )
    assert "REVIEW_SENTINEL_SECRET" not in repr(result)
    assert PAGE_ID not in repr(result)
