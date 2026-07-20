from __future__ import annotations

import json

import pytest

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.rules.confluence_page_observations import (
    ConfluencePageObservationPayloadError,
    build_restriction_observation,
    extract_ordered_restriction_targets,
    parse_attachment_metadata_window,
)

PAGE_ID = "1000"


def _page(*, ancestors: object, page_id: object = PAGE_ID) -> bytes:
    return json.dumps({"id": page_id, "ancestors": ancestors}).encode()


def _attachment_page(
    *, results: object, next_link: object = None, size: int = 0
) -> bytes:
    links = {} if next_link is None else {"next": next_link}
    return json.dumps(
        {"results": results, "size": size, "limit": 2, "_links": links}
    ).encode()


def test_extracts_ordered_ancestors_and_appends_selected_page() -> None:
    assert extract_ordered_restriction_targets(
        raw_page=_page(ancestors=[{"id": "7"}, {"id": 8}]),
        selected_page_id=PAGE_ID,
    ) == ("7", "8", PAGE_ID)


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"[]",
        _page(ancestors={}, page_id=PAGE_ID),
        _page(ancestors=[{"id": "7"}, {"id": "7"}]),
        _page(ancestors=[{"id": PAGE_ID}]),
        _page(ancestors=[{"id": "bad"}]),
        _page(ancestors=[], page_id="9999"),
    ],
)
def test_rejects_invalid_raw_page_before_collection(raw: bytes) -> None:
    with pytest.raises(ConfluencePageObservationPayloadError):
        extract_ordered_restriction_targets(
            raw_page=raw,
            selected_page_id=PAGE_ID,
        )


def _restriction_payload(*, users: list[object], groups: list[object]) -> bytes:
    return json.dumps(
        {
            "operation": "view",
            "restrictions": {
                "user": {"results": users},
                "group": {"results": groups},
            },
        }
    ).encode()


def test_valid_empty_restriction_set_is_unrestricted() -> None:
    result = build_restriction_observation(
        target_page_id=PAGE_ID,
        response=RawHttpObservation(
            status_code=200,
            body=_restriction_payload(users=[], groups=[]),
        ),
    )

    assert result["classification"] == "unrestricted"
    assert result["users"] == []
    assert result["groups"] == []


def test_valid_restriction_preserves_principal_identifiers_exactly() -> None:
    result = build_restriction_observation(
        target_page_id=PAGE_ID,
        response=RawHttpObservation(
            status_code=200,
            body=_restriction_payload(
                users=[{"username": "synthetic-user", "userKey": "key-1"}],
                groups=[{"name": "synthetic-group"}],
            ),
        ),
    )

    assert result == {
        "source_page_id": PAGE_ID,
        "http_status": 200,
        "classification": "restricted",
        "users": [{"username": "synthetic-user", "userKey": "key-1"}],
        "groups": [{"name": "synthetic-group"}],
    }
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_expected_non_success_restriction_is_unavailable(status: int) -> None:
    result = build_restriction_observation(
        target_page_id=PAGE_ID,
        response=RawHttpObservation(status_code=status, body=b"not-json"),
    )

    assert result["classification"] == "unavailable"
    assert result["users"] == []
    assert result["groups"] == []


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-json",
        b"[]",
        b'{"operation":"edit","restrictions":{}}',
        b'{"operation":"view","restrictions":{}}',
        _restriction_payload(users=[{"displayName": "not-an-identifier"}], groups=[]),
    ],
)
def test_malformed_200_restriction_is_unavailable_not_unrestricted(body: bytes) -> None:
    result = build_restriction_observation(
        target_page_id=PAGE_ID,
        response=RawHttpObservation(status_code=200, body=body),
    )
    assert result["classification"] == "unavailable"


def test_unexpected_restriction_status_is_not_disguised_as_unavailable() -> None:
    with pytest.raises(ConfluencePageObservationPayloadError):
        build_restriction_observation(
            target_page_id=PAGE_ID,
            response=RawHttpObservation(status_code=500, body=b"synthetic failure"),
        )


def test_body_bearing_domain_results_have_sanitized_repr() -> None:
    raw = RawHttpObservation(status_code=404, body=b"private-synthetic-body")
    parsed = parse_attachment_metadata_window(
        raw_bytes=_attachment_page(
            results=[{"id": "2000", "title": "private-synthetic-file"}]
        ),
        selected_page_id=PAGE_ID,
        request=AttachmentMetadataRequest(start=0, limit=2),
    )
    assert "private-synthetic-body" not in repr(raw)
    assert "private-synthetic-file" not in repr(parsed)


def test_attachment_window_normalizes_metadata_and_follows_observed_next() -> None:
    raw = _attachment_page(
        results=[
            {
                "id": "2000",
                "type": "attachment",
                "status": "current",
                "title": "synthetic.pdf",
                "metadata": {"mediaType": "application/pdf"},
                "extensions": {"fileSize": 123},
                "version": {"number": 2},
                "_links": {"download": "/download/attachments/never-follow"},
            }
        ],
        next_link="/rest/api/content/1000/child/attachment?start=7&limit=3",
        size=1,
    )

    parsed = parse_attachment_metadata_window(
        raw_bytes=raw,
        selected_page_id=PAGE_ID,
        request=AttachmentMetadataRequest(start=0, limit=2),
    )

    assert parsed.attachments == (
        {
            "source_page_id": PAGE_ID,
            "attachment_id": "2000",
            "filename": "synthetic.pdf",
            "status": "current",
            "media_type": "application/pdf",
            "file_size": 123,
            "version_number": 2,
        },
    )
    assert parsed.next_request == AttachmentMetadataRequest(start=7, limit=3)
    json.dumps(parsed.attachments, allow_nan=False)


def test_short_window_does_not_terminate_when_observed_next_exists() -> None:
    parsed = parse_attachment_metadata_window(
        raw_bytes=_attachment_page(
            results=[],
            next_link="/rest/api/content/1000/child/attachment?start=9&limit=2",
            size=0,
        ),
        selected_page_id=PAGE_ID,
        request=AttachmentMetadataRequest(start=0, limit=2),
    )
    assert parsed.next_request == AttachmentMetadataRequest(start=9, limit=2)


def test_full_window_terminates_when_next_is_absent() -> None:
    parsed = parse_attachment_metadata_window(
        raw_bytes=_attachment_page(
            results=[{"id": "2000", "title": "a"}], size=2
        ),
        selected_page_id=PAGE_ID,
        request=AttachmentMetadataRequest(start=0, limit=2),
    )
    assert parsed.next_request is None


def test_explicit_null_next_is_invalid_not_a_termination_signal() -> None:
    raw = json.dumps({"results": [], "_links": {"next": None}}).encode()
    with pytest.raises(ConfluencePageObservationPayloadError):
        parse_attachment_metadata_window(
            raw_bytes=raw,
            selected_page_id=PAGE_ID,
            request=AttachmentMetadataRequest(start=0, limit=2),
        )


@pytest.mark.parametrize(
    "next_link",
    [
        "https://other.invalid/rest/api/content/1000/child/attachment?start=2&limit=2",
        "/rest/api/content/9999/child/attachment?start=2&limit=2",
        "/rest/api/content/1000/child/page?start=2&limit=2",
        "/rest/api/content/1000/child/attachment?start=0&limit=2",
        "/rest/api/content/1000/child/attachment?start=2&limit=2&download=true",
        "/rest/api/content/1000/child/attachment?start=02&limit=2",
        "\n/rest/api/content/1000/child/attachment?start=2&limit=2",
    ],
)
def test_rejects_unsafe_or_nonadvancing_next_link(next_link: str) -> None:
    with pytest.raises(ConfluencePageObservationPayloadError):
        parse_attachment_metadata_window(
            raw_bytes=_attachment_page(results=[], next_link=next_link),
            selected_page_id=PAGE_ID,
            request=AttachmentMetadataRequest(start=0, limit=2),
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"[]",
        b"{}",
        b'{"results":{}}',
        _attachment_page(results=[{"id": "2000", "title": "a"}, {"id": "2000", "title": "b"}]),
        _attachment_page(results=[{"id": "bad", "title": "a"}]),
    ],
)
def test_rejects_malformed_attachment_window(raw: bytes) -> None:
    with pytest.raises(ConfluencePageObservationPayloadError):
        parse_attachment_metadata_window(
            raw_bytes=raw,
            selected_page_id=PAGE_ID,
            request=AttachmentMetadataRequest(start=0, limit=2),
        )
