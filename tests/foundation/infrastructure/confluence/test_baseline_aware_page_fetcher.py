import pytest

from knowledgenexus.foundation.infrastructure.confluence.baseline_aware_page_fetcher import (
    BaselineAwarePageFetcher,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchError,
)


class _RecordingFetcher:
    def __init__(self, body: bytes = b'{"live": true}') -> None:
        self.calls: list[str] = []
        self._body = body

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        self.calls.append(page_id)
        return self._body


def test_unchanged_page_is_served_from_baseline_without_a_live_call():
    inner = _RecordingFetcher()
    fetcher = BaselineAwarePageFetcher(inner=inner, baseline_bodies={"12345": b"baseline-body"})

    assert fetcher.fetch_page_raw(page_id="12345") == b"baseline-body"
    assert inner.calls == []
    assert fetcher.reused_pages == 1
    assert fetcher.fetched_pages == 0


def test_page_not_in_baseline_is_fetched_live():
    inner = _RecordingFetcher(body=b"live-body")
    fetcher = BaselineAwarePageFetcher(inner=inner, baseline_bodies={"12345": b"baseline-body"})

    assert fetcher.fetch_page_raw(page_id="67890") == b"live-body"
    assert inner.calls == ["67890"]
    assert fetcher.reused_pages == 0
    assert fetcher.fetched_pages == 1


def test_mixed_batch_counts_reuse_and_live_separately():
    inner = _RecordingFetcher()
    fetcher = BaselineAwarePageFetcher(inner=inner, baseline_bodies={"1": b"a", "2": b"b"})

    fetcher.fetch_page_raw(page_id="1")
    fetcher.fetch_page_raw(page_id="3")
    fetcher.fetch_page_raw(page_id="2")

    assert inner.calls == ["3"]
    assert (fetcher.reused_pages, fetcher.fetched_pages) == (2, 1)


def test_live_fetch_errors_propagate():
    class _Broken:
        def fetch_page_raw(self, *, page_id: str) -> bytes:
            raise ConfluencePageFetchError("boom")

    fetcher = BaselineAwarePageFetcher(inner=_Broken(), baseline_bodies={})
    with pytest.raises(ConfluencePageFetchError):
        fetcher.fetch_page_raw(page_id="9")


def test_empty_or_non_bytes_baseline_body_is_rejected():
    with pytest.raises(ValueError):
        BaselineAwarePageFetcher(inner=_RecordingFetcher(), baseline_bodies={"1": b""})
    with pytest.raises(ValueError):
        BaselineAwarePageFetcher(inner=_RecordingFetcher(), baseline_bodies={"1": "x"})  # type: ignore[dict-item]
