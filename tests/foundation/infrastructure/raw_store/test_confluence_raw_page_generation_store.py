from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")
OTHER_RUN_ID = CrawlRunId("87654321-4321-4234-9234-cba987654321")


def _envelope(
    *,
    run_id: CrawlRunId = RUN_ID,
    page_id: str = "1000",
    source_version: str | None = "v1",
    status: int = 200,
    body: bytes = b"body",
) -> ConfluenceRawPageEnvelope:
    return ConfluenceRawPageEnvelope.capture(
        run_id=run_id,
        page_id=page_id,
        source_version=source_version,
        http_status=status,
        body_bytes=body,
    )


def _store(tmp_path: Path) -> ConfluenceRawPageGenerationStore:
    return ConfluenceRawPageGenerationStore(raw_root=tmp_path)


def _category(callable_, *args, **kwargs):
    with pytest.raises(ConfluenceRawPageStoreError) as exc_info:
        callable_(*args, **kwargs)
    return exc_info.value.category


def test_invalid_root_uses_page_store_error_boundary(tmp_path: Path) -> None:
    with pytest.raises(ConfluenceRawPageStoreError) as exc_info:
        ConfluenceRawPageGenerationStore(raw_root=tmp_path / "missing")

    assert exc_info.value.category.value == "raw_artifact_invalid"


def test_publish_resolves_generation_path_and_reads_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope(body=b"\x00\xff")

    result = store.publish_page(envelope=envelope)
    expected = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )

    assert result.path == expected
    assert result.outcome is ConfluenceRawPagePublicationOutcome.PUBLISHED
    assert expected.read_bytes() == envelope.to_bytes()
    assert store.read_page(run_id=RUN_ID, page_id="1000") == envelope


def test_identical_same_run_replay_reuses_without_replacement(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope()
    first = store.publish_page(envelope=envelope)
    before = first.path.stat()

    second = store.publish_page(envelope=envelope)
    after = second.path.stat()

    assert second.outcome is ConfluenceRawPagePublicationOutcome.REUSED
    assert second.path == first.path
    assert (after.st_ino, after.st_size) == (before.st_ino, before.st_size)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": b"different"},
        {"status": 404},
        {"source_version": "v2"},
    ],
)
def test_differing_same_run_evidence_fails_closed(tmp_path: Path, kwargs: dict) -> None:
    store = _store(tmp_path)
    store.publish_page(envelope=_envelope())

    category = _category(store.publish_page, envelope=_envelope(**kwargs))

    assert category.value == "raw_replay_conflict"


def test_distinct_generation_uses_distinct_path(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.publish_page(envelope=_envelope())
    second = store.publish_page(envelope=_envelope(run_id=OTHER_RUN_ID))

    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


def test_path_envelope_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.publish_page(envelope=_envelope())
    first.path.write_bytes(_envelope(page_id="1001").to_bytes())

    category = _category(store.read_page, run_id=RUN_ID, page_id="1000")

    assert category.value == "raw_identity_mismatch"


def test_malformed_target_is_not_rewritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = store.resolve_page_path(run_id=RUN_ID, page_id="1000")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-json")

    category = _category(store.publish_page, envelope=_envelope())

    assert category.value == "raw_artifact_invalid"
    assert target.read_bytes() == b"not-json"


def test_concurrent_identical_creators_publish_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    envelope = _envelope()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _index: store.publish_page(envelope=envelope), range(2))
        )

    assert sorted(result.outcome.value for result in results) == ["published", "reused"]
