from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.collect_confluence_page_observations import (
    CollectConfluencePageObservations,
    PageObservationCollectionError,
)
from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
    RawHttpObservation,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
)

PAGE_ID = "1000"


class FakeAdapter:
    def __init__(self, attachment_bodies: dict[AttachmentMetadataRequest, bytes]) -> None:
        self.attachment_bodies = attachment_bodies
        self.restriction_calls: list[str] = []
        self.attachment_calls: list[AttachmentMetadataRequest] = []

    def fetch_view_restriction(self, *, page_id: str) -> RawHttpObservation:
        self.restriction_calls.append(page_id)
        return RawHttpObservation(status_code=404, body=f"missing-{page_id}".encode())

    def fetch_attachment_metadata(
        self, *, page_id: str, request: AttachmentMetadataRequest
    ) -> bytes:
        self.attachment_calls.append(request)
        return self.attachment_bodies[request]


def _write_page(root: Path, raw: bytes) -> None:
    path = root / "confluence" / "pages" / f"{PAGE_ID}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)


def _page(ancestors: object = None) -> bytes:
    if ancestors is None:
        ancestors = [{"id": "900"}, {"id": "901"}]
    return json.dumps({"id": PAGE_ID, "ancestors": ancestors}).encode()


def _window(
    *, attachment_id: str | None = None, next_link: str | None = None
) -> bytes:
    results = []
    if attachment_id is not None:
        results.append(
            {
                "id": attachment_id,
                "type": "attachment",
                "title": f"synthetic-{attachment_id}.bin",
                "metadata": {"mediaType": "application/octet-stream"},
            }
        )
    links = {} if next_link is None else {"next": next_link}
    return json.dumps({"results": results, "_links": links}).encode()


def _use_case(
    root: Path,
    adapter: FakeAdapter,
    *,
    max_pages: int = 10,
) -> CollectConfluencePageObservations:
    store = ConfluencePageObservationStore(raw_root=root)
    return CollectConfluencePageObservations(
        raw_page_reader=store,
        restriction_fetcher=adapter,
        attachment_fetcher=adapter,
        raw_observation_store=store,
        attachment_page_size=2,
        max_attachment_pages=max_pages,
    )


def test_success_preserves_order_exact_bodies_and_observations(tmp_path: Path) -> None:
    _write_page(tmp_path, _page())
    first = AttachmentMetadataRequest(start=0, limit=2)
    second = AttachmentMetadataRequest(start=7, limit=3)
    first_raw = _window(
        attachment_id="2000",
        next_link="/rest/api/content/1000/child/attachment?start=7&limit=3",
    )
    second_raw = _window(attachment_id="2001")
    adapter = FakeAdapter({first: first_raw, second: second_raw})

    result = _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert adapter.restriction_calls == ["900", "901", PAGE_ID]
    assert [o["classification"] for o in result.restriction_observations] == [
        "unavailable",
        "unavailable",
        "unavailable",
    ]
    assert adapter.attachment_calls == [first, second]
    assert result.attachment_window_count == 2
    assert [o["attachment_id"] for o in result.attachment_observations] == [
        "2000",
        "2001",
    ]
    assert "2000" not in repr(result)
    assert "synthetic" not in repr(result)
    json.dumps(result.restriction_observations, allow_nan=False)
    json.dumps(result.attachment_observations, allow_nan=False)

    restriction_root = tmp_path / "confluence" / "restrictions" / "view" / PAGE_ID
    assert (restriction_root / "900.body").read_bytes() == b"missing-900"
    assert (restriction_root / "901.body").read_bytes() == b"missing-901"
    assert (restriction_root / "1000.body").read_bytes() == b"missing-1000"
    attachment_root = tmp_path / "confluence" / "attachments" / "metadata" / PAGE_ID
    assert (attachment_root / "start-0_limit-2.json").read_bytes() == first_raw
    assert (attachment_root / "start-7_limit-3.json").read_bytes() == second_raw


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"not-json",
        b"[]",
        b'{"id":"9999","ancestors":[]}',
        b'{"id":"1000","ancestors":[{"id":"bad"}]}',
        b'{"id":"1000","ancestors":[{"id":"900"},{"id":"900"}]}',
    ],
)
def test_invalid_or_missing_page_causes_zero_network_calls(
    tmp_path: Path, raw: bytes | None
) -> None:
    if raw is not None:
        _write_page(tmp_path, raw)
    adapter = FakeAdapter({})

    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "raw_page_input"
    assert adapter.restriction_calls == []
    assert adapter.attachment_calls == []


def test_multi_window_cycle_is_rejected_before_repeated_request(tmp_path: Path) -> None:
    _write_page(tmp_path, _page([]))
    first = AttachmentMetadataRequest(start=0, limit=2)
    second = AttachmentMetadataRequest(start=2, limit=2)
    adapter = FakeAdapter(
        {
            first: _window(
                next_link="/rest/api/content/1000/child/attachment?start=2&limit=2"
            ),
            second: _window(
                next_link="/rest/api/content/1000/child/attachment?start=0&limit=2"
            ),
        }
    )

    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "pagination"
    assert adapter.attachment_calls == [first, second]


def test_safety_ceiling_stops_before_fetching_another_window(tmp_path: Path) -> None:
    _write_page(tmp_path, _page([]))
    first = AttachmentMetadataRequest(start=0, limit=2)
    adapter = FakeAdapter(
        {
            first: _window(
                next_link="/rest/api/content/1000/child/attachment?start=2&limit=2"
            )
        }
    )

    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter, max_pages=1).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "pagination"
    assert adapter.attachment_calls == [first]


def test_duplicate_attachment_across_windows_fails_closed(tmp_path: Path) -> None:
    _write_page(tmp_path, _page([]))
    first = AttachmentMetadataRequest(start=0, limit=2)
    second = AttachmentMetadataRequest(start=2, limit=2)
    adapter = FakeAdapter(
        {
            first: _window(
                attachment_id="2000",
                next_link="/rest/api/content/1000/child/attachment?start=2&limit=2",
            ),
            second: _window(attachment_id="2000"),
        }
    )

    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "attachment_payload"
    assert adapter.attachment_calls == [first, second]


def test_malformed_attachment_window_is_preserved_then_stops(tmp_path: Path) -> None:
    _write_page(tmp_path, _page([]))
    request = AttachmentMetadataRequest(start=0, limit=2)
    raw = b"not-json-exact"
    adapter = FakeAdapter({request: raw})

    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "attachment_payload"
    target = (
        tmp_path
        / "confluence"
        / "attachments"
        / "metadata"
        / PAGE_ID
        / "start-0_limit-2.json"
    )
    assert target.read_bytes() == raw


def test_unexpected_restriction_status_is_preserved_then_fails_operationally(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path, _page([]))

    class Unexpected(FakeAdapter):
        def fetch_view_restriction(self, *, page_id: str) -> RawHttpObservation:
            self.restriction_calls.append(page_id)
            return RawHttpObservation(status_code=500, body=b"synthetic-500-body")

    adapter = Unexpected({})
    with pytest.raises(PageObservationCollectionError) as exc_info:
        _use_case(tmp_path, adapter).execute(selected_page_id=PAGE_ID)

    assert exc_info.value.category == "restriction_http"
    target = (
        tmp_path
        / "confluence"
        / "restrictions"
        / "view"
        / PAGE_ID
        / f"{PAGE_ID}.body"
    )
    assert target.read_bytes() == b"synthetic-500-body"
    assert adapter.attachment_calls == []
