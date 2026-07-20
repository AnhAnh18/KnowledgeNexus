from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.fetch_raw_confluence_page import (  # noqa: E501
    FetchRawConfluencePage,
    RawPageFetchError,
    RawPageFetchResult,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageStore
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchError,
    ConfluencePageTooLargeError,
)

PAGE_ID = "1000"
RAW = '{"id":"1000","title":"T  ","body":{"storage":{"value":"<p>x</p>"}}}  \n'.encode()
# Real multibyte UTF-8 bytes (café, 世界) alongside an escaped sequence, so
# byte fidelity is exercised on actual non-ASCII bytes, not just "\u..." text.
RAW_UNICODE = (
    '{"id":"1000","title":"café 世界","body":'
    '{"storage":{"value":"<p>na\\u00efve</p>"}}}'
).encode("utf-8")


class FakeFetcher:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        return self.body


class RaisingFetcher:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        raise self.error


def _use_case(tmp_path: Path, fetcher: object) -> FetchRawConfluencePage:
    return FetchRawConfluencePage(
        page_fetcher=fetcher,  # type: ignore[arg-type]
        raw_page_store=ConfluenceRawPageStore(raw_root=tmp_path),
    )


def test_success_persists_exact_bytes_and_returns_minimal_metadata(
    tmp_path: Path,
) -> None:
    result = _use_case(tmp_path, FakeFetcher(RAW)).execute(page_id=PAGE_ID)

    assert isinstance(result, RawPageFetchResult)
    artifact = result.artifact
    assert artifact.path.read_bytes() == RAW  # exact, not reserialized
    assert artifact.raw_sha256 == hashlib.sha256(RAW).hexdigest()
    assert artifact.byte_count == len(RAW)
    # The result exposes no raw content.
    assert not hasattr(result, "raw_bytes")


def test_http_failure_maps_to_http_and_writes_no_artifact(tmp_path: Path) -> None:
    use_case = _use_case(
        tmp_path, RaisingFetcher(ConfluencePageFetchError("page fetch failed"))
    )

    with pytest.raises(RawPageFetchError) as exc_info:
        use_case.execute(page_id=PAGE_ID)

    assert exc_info.value.category == "http"
    assert not (tmp_path / "confluence").exists()


def test_oversize_maps_to_response_size_limit_and_writes_no_artifact(
    tmp_path: Path,
) -> None:
    use_case = _use_case(
        tmp_path, RaisingFetcher(ConfluencePageTooLargeError("too large"))
    )

    with pytest.raises(RawPageFetchError) as exc_info:
        use_case.execute(page_id=PAGE_ID)

    assert exc_info.value.category == "response_size_limit"
    assert not (tmp_path / "confluence").exists()


def test_real_multibyte_unicode_bytes_are_preserved_exactly(tmp_path: Path) -> None:
    result = _use_case(tmp_path, FakeFetcher(RAW_UNICODE)).execute(page_id=PAGE_ID)

    on_disk = result.artifact.path.read_bytes()
    assert on_disk == RAW_UNICODE
    assert "café".encode("utf-8") in on_disk
    assert "世界".encode("utf-8") in on_disk
    assert b"\\u00ef" in on_disk  # the escaped sequence stays a literal escape
    assert result.artifact.raw_sha256 == hashlib.sha256(RAW_UNICODE).hexdigest()


def test_malformed_json_maps_and_writes_no_artifact(tmp_path: Path) -> None:
    with pytest.raises(RawPageFetchError) as exc_info:
        _use_case(tmp_path, FakeFetcher(b"not-json")).execute(page_id=PAGE_ID)

    assert exc_info.value.category == "malformed_json"
    assert not (tmp_path / "confluence").exists()


def test_non_object_json_maps_and_writes_no_artifact(tmp_path: Path) -> None:
    with pytest.raises(RawPageFetchError) as exc_info:
        _use_case(tmp_path, FakeFetcher(b"[1,2,3]")).execute(page_id=PAGE_ID)

    assert exc_info.value.category == "non_object_json"
    assert not (tmp_path / "confluence").exists()


@pytest.mark.parametrize(
    "body",
    [
        b'{"id":"9999"}',
        b'{"id":9999}',
        b'{"nope":"1000"}',
        b'{"id":true}',
        b'{"id":null}',
    ],
)
def test_identity_mismatch_fails_closed(tmp_path: Path, body: bytes) -> None:
    with pytest.raises(RawPageFetchError) as exc_info:
        _use_case(tmp_path, FakeFetcher(body)).execute(page_id=PAGE_ID)

    assert exc_info.value.category == "identity_mismatch"
    assert not (tmp_path / "confluence").exists()


@pytest.mark.parametrize("body", [b'{"id":"1000"}', b'{"id":1000}'])
def test_string_or_int_id_matches_by_string_equality(
    tmp_path: Path, body: bytes
) -> None:
    # The plan compares str(response id) == requested page id, so a numeric JSON
    # id of 1000 matches the requested "1000".
    result = _use_case(tmp_path, FakeFetcher(body)).execute(page_id=PAGE_ID)
    assert result.artifact.byte_count == len(body)


@pytest.mark.parametrize("page_id", ["../secret", "a1", "", "1 0"])
def test_invalid_page_id_maps_and_never_fetches(tmp_path: Path, page_id: str) -> None:
    class Tripwire:
        def fetch_page_raw(self, *, page_id: str) -> bytes:
            raise AssertionError("must not fetch on invalid page id")

    with pytest.raises(RawPageFetchError) as exc_info:
        _use_case(tmp_path, Tripwire()).execute(page_id=page_id)

    assert exc_info.value.category == "invalid_page_id"


def test_store_failure_maps_to_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledgenexus.foundation.infrastructure.raw_store import (
        confluence_raw_page_store as store_module,
    )

    def boom(fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(store_module.os, "fsync", boom)

    with pytest.raises(RawPageFetchError) as exc_info:
        _use_case(tmp_path, FakeFetcher(RAW)).execute(page_id=PAGE_ID)

    assert exc_info.value.category == "store"
