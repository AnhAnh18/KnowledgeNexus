from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_raw_page_generation import (
    FetchAndStoreConfluenceRawPageGeneration,
    GenerationRawPageFetchError,
    GenerationRawPageFetchResult,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_generation_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchError,
    ConfluencePageTooLargeError,
)


RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
RAW = (
    b'{"id":"1000","version":{"number":7},"body":{"storage":'
    b'{"value":"<p>x</p>"}}}'
)


class Fetcher:
    def __init__(self, body: bytes | None = RAW, error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls: list[str] = []

    def fetch_page_raw(self, *, page_id: str) -> bytes:
        self.calls.append(page_id)
        if self.error is not None:
            raise self.error
        assert self.body is not None
        return self.body


def _use_case(tmp_path: Path, fetcher: object) -> FetchAndStoreConfluenceRawPageGeneration:
    return FetchAndStoreConfluenceRawPageGeneration(
        page_fetcher=fetcher,  # type: ignore[arg-type]
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=tmp_path),
    )


def test_publishes_exact_bytes_with_source_version_and_generation_identity(tmp_path: Path) -> None:
    fetcher = Fetcher()
    result = _use_case(tmp_path, fetcher).execute(run_id=RUN, page_id="1000")

    assert isinstance(result, GenerationRawPageFetchResult)
    envelope = ConfluenceRawPageGenerationStore(raw_root=tmp_path).read_page(
        run_id=RUN, page_id="1000"
    )
    assert envelope.body_bytes == RAW
    assert envelope.source_version == "7"
    assert envelope.http_status == 200
    assert result.artifact.byte_count == len(envelope.to_bytes())
    assert result.artifact.raw_sha256 == hashlib.sha256(envelope.to_bytes()).hexdigest()
    assert fetcher.calls == ["1000"]


@pytest.mark.parametrize(
    ("body", "category"),
    [
        (b"not-json", "malformed_json"),
        (b"[]", "non_object_json"),
        (b'{"id":"999","version":{"number":7}}', "identity_mismatch"),
        (b'{"id":"1000","version":{}}', "source_version_invalid"),
        (b'{"id":"1000","version":{"number":0}}', "source_version_invalid"),
    ],
)
def test_rejects_invalid_page_evidence_without_store_write(
    tmp_path: Path, body: bytes, category: str
) -> None:
    with pytest.raises(GenerationRawPageFetchError) as exc_info:
        _use_case(tmp_path, Fetcher(body=body)).execute(run_id=RUN, page_id="1000")
    assert exc_info.value.category == category
    assert not (tmp_path / "confluence").exists()


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (ConfluencePageTooLargeError("too large"), "response_size_limit"),
        (ConfluencePageFetchError("secret"), "http"),
    ],
)
def test_maps_fetch_failures_without_leaking_details(
    tmp_path: Path, error: Exception, category: str
) -> None:
    with pytest.raises(GenerationRawPageFetchError) as exc_info:
        _use_case(tmp_path, Fetcher(error=error)).execute(run_id=RUN, page_id="1000")
    assert exc_info.value.category == category
    assert "secret" not in str(exc_info.value)


def test_invalid_identity_fails_before_fetch(tmp_path: Path) -> None:
    fetcher = Fetcher()
    with pytest.raises(GenerationRawPageFetchError) as exc_info:
        _use_case(tmp_path, fetcher).execute(run_id=object(), page_id="1000")  # type: ignore[arg-type]
    assert exc_info.value.category == "invalid_run_id"
    assert fetcher.calls == []

    with pytest.raises(GenerationRawPageFetchError) as exc_info:
        _use_case(tmp_path, fetcher).execute(run_id=RUN, page_id="../secret")
    assert exc_info.value.category == "invalid_page_id"
    assert fetcher.calls == []
