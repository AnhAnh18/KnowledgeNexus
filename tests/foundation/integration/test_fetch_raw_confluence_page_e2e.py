from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.fetch_raw_confluence_page import (  # noqa: E501
    FetchRawConfluencePage,
    RawPageFetchError,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceDataCenterPageAdapter,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageStore

PAGE_ID = "1000"
# A realistic-shaped but synthetic page: the endpoint/expand shape is confirmed
# by approved M6-0; the content here is synthetic and contains awkward bytes
# (unicode escape, double spaces, embedded newline, unsorted keys, trailing).
SYNTHETIC_PAGE = (
    '{"id":"1000","type":"page","status":"current","title":"Synthetic  Page",'
    '"space":{"key":"SPACE"},"version":{"number":7},'
    '"body":{"storage":{"value":"<p>a  b</p>\\n<ac:structured-macro/>",'
    '"representation":"storage"}},'
    '"ancestors":[{"id":"900"}],"metadata":{"labels":{"results":[]}},'
    '"z_trailing":true}  \n'
).encode("utf-8")


class FakeTransport:
    """Fake at the transport seam; the adapter/use-case/store are production."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[dict[str, object]] = []

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        self.calls.append({"path": path, "query": dict(query)})
        return self.body

    def get_json(self, *, path: str, query: Mapping[str, str]) -> Mapping[str, object]:
        raise AssertionError("M6A must fetch raw bytes, never get_json")


def _run(tmp_path: Path, transport: FakeTransport) -> object:
    use_case = FetchRawConfluencePage(
        page_fetcher=ConfluenceDataCenterPageAdapter(transport=transport),
        raw_page_store=ConfluenceRawPageStore(raw_root=tmp_path),
    )
    return use_case.execute(page_id=PAGE_ID)


def test_end_to_end_fetch_preserves_exact_bytes_path_and_hash(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(SYNTHETIC_PAGE)

    result = _run(tmp_path, transport)

    # One confirmed page GET, no other endpoint.
    assert transport.calls == [
        {
            "path": "/rest/api/content/1000",
            "query": {"expand": "body.storage,space,version,ancestors,metadata.labels"},
        }
    ]
    artifact = result.artifact
    # Deterministic path.
    assert artifact.path == tmp_path.resolve() / "confluence" / "pages" / "1000.json"
    # Exact bytes on disk, byte-for-byte.
    assert artifact.path.read_bytes() == SYNTHETIC_PAGE
    # Raw hash over the exact bytes.
    assert artifact.raw_sha256 == hashlib.sha256(SYNTHETIC_PAGE).hexdigest()
    assert artifact.byte_count == len(SYNTHETIC_PAGE)


def test_end_to_end_second_run_atomically_replaces_the_first(
    tmp_path: Path,
) -> None:
    first = _run(tmp_path, FakeTransport(b'{"id":"1000","v":1}'))
    assert first.artifact.path.read_bytes() == b'{"id":"1000","v":1}'

    second = _run(tmp_path, FakeTransport(SYNTHETIC_PAGE))

    assert second.artifact.path == first.artifact.path
    assert second.artifact.path.read_bytes() == SYNTHETIC_PAGE
    # Deterministic path means exactly one artifact, replaced in place.
    assert sorted(p.name for p in second.artifact.path.parent.iterdir()) == [
        "1000.json"
    ]


def test_end_to_end_identity_mismatch_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(RawPageFetchError) as exc_info:
        _run(tmp_path, FakeTransport(b'{"id":"2222","title":"other"}'))

    assert exc_info.value.category == "identity_mismatch"
    assert not (tmp_path / "confluence").exists()
