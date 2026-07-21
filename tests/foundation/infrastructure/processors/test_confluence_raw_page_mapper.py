from __future__ import annotations

import json

import pytest

from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMappingError,
)

PAGE_ID = "1000"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": PAGE_ID,
        "type": "page",
        "title": "Fixture Foundation",
        "space": {"key": "SPACE"},
        "version": {"number": 7, "when": "2026-07-21T01:02:03Z"},
        "body": {
            "storage": {
                "value": "<p>Fixture body</p>",
                "representation": "storage",
            }
        },
    }
    payload.update(overrides)
    return payload


def _raw(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_maps_trusted_page_fields_without_mutating_storage() -> None:
    mapper = ConfluenceDataCenterRawPageMapper()

    result = mapper.map_page(raw_bytes=_raw(_payload()), expected_page_id=PAGE_ID)

    assert result.page_id == PAGE_ID
    assert result.title == "Fixture Foundation"
    assert result.space_key == "SPACE"
    assert result.source_version == "7"
    assert result.updated_at == "2026-07-21T01:02:03Z"
    assert result.storage_xhtml == "<p>Fixture body</p>"
    assert "Fixture body" not in repr(result)


def test_accepts_numeric_json_page_id_but_returns_canonical_string() -> None:
    result = ConfluenceDataCenterRawPageMapper().map_page(
        raw_bytes=_raw(_payload(id=1000)),
        expected_page_id=PAGE_ID,
    )
    assert result.page_id == PAGE_ID


@pytest.mark.parametrize(
    ("raw_bytes", "expected_message"),
    [
        (b"\xff", "raw page must be valid UTF-8 JSON"),
        (b"{", "raw page must be valid UTF-8 JSON"),
        (_raw([]), "raw page JSON must be an object"),
    ],
)
def test_rejects_invalid_json_envelopes(
    raw_bytes: bytes,
    expected_message: str,
) -> None:
    with pytest.raises(ConfluenceRawPageMappingError, match=expected_message):
        ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=raw_bytes,
            expected_page_id=PAGE_ID,
        )


@pytest.mark.parametrize("page_id", [None, True, "", "abc", -1])
def test_rejects_invalid_or_mismatched_identity(page_id: object) -> None:
    payload = _payload(id=page_id)
    with pytest.raises(ConfluenceRawPageMappingError):
        ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=_raw(payload),
            expected_page_id=PAGE_ID,
        )


def test_rejects_mismatched_identity() -> None:
    with pytest.raises(
        ConfluenceRawPageMappingError,
        match="page response identity does not match",
    ):
        ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=_raw(_payload(id="2000")),
            expected_page_id=PAGE_ID,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "blogpost"},
        {"title": None},
        {"title": "   "},
        {"space": None},
        {"space": {}},
        {"space": {"key": ""}},
        {"version": None},
        {"version": {"number": True, "when": "2026-07-21T01:02:03Z"}},
        {"version": {"number": 0, "when": "2026-07-21T01:02:03Z"}},
        {"version": {"number": 1}},
        {"body": None},
        {"body": {}},
        {"body": {"storage": None}},
        {"body": {"storage": {"representation": "storage"}}},
        {"body": {"storage": {"value": "", "representation": "view"}}},
    ],
)
def test_rejects_missing_or_untrusted_required_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ConfluenceRawPageMappingError):
        ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=_raw(_payload(**overrides)),
            expected_page_id=PAGE_ID,
        )


def test_exceptions_do_not_disclose_source_values() -> None:
    sensitive = "REVIEW_SENTINEL_SECRET_TITLE"
    payload = _payload(title=sensitive, space={"key": None})

    with pytest.raises(ConfluenceRawPageMappingError) as caught:
        ConfluenceDataCenterRawPageMapper().map_page(
            raw_bytes=_raw(payload),
            expected_page_id=PAGE_ID,
        )

    assert sensitive not in str(caught.value)
    assert PAGE_ID not in str(caught.value)
