from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.infrastructure.raw_store.budgeted_confluence_raw_page_store import (
    BudgetedConfluenceRawPageStore,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_page_generation_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
)


RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")


def _envelope() -> ConfluenceRawPageEnvelope:
    return ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID,
        page_id="1000",
        source_version="v1",
        http_status=200,
        body_bytes=b"bounded",
    )


def _store(tmp_path: Path, **kwargs: object) -> BudgetedConfluenceRawPageStore:
    guard_lock = kwargs.pop("guard_lock", Lock())

    @contextmanager
    def guard():
        if not guard_lock.acquire(blocking=False):
            raise RuntimeError("writer lease unavailable")
        try:
            yield
        finally:
            guard_lock.release()

    return BudgetedConfluenceRawPageStore(
        inner=ConfluenceRawPageGenerationStore(raw_root=tmp_path),
        raw_root=tmp_path,
        publication_guard=guard,
        max_total_bytes=kwargs.pop("max_total_bytes", 1024 * 1024),
        minimum_free_disk_reserve_bytes=kwargs.pop(
            "minimum_free_disk_reserve_bytes", 0
        ),
        **kwargs,
    )


def test_total_byte_budget_fails_before_publication(tmp_path: Path) -> None:
    serialized = _envelope().to_bytes()
    store = _store(tmp_path, max_total_bytes=len(serialized) - 1)

    with pytest.raises(ConfluenceRawPageStoreError) as exc_info:
        store.publish_page(envelope=_envelope())

    assert exc_info.value.category.value == "raw_publication_failure"
    assert not store.resolve_page_path(run_id=RUN_ID, page_id="1000").exists()


def test_disk_reserve_fails_before_publication(tmp_path: Path) -> None:
    serialized = _envelope().to_bytes()
    store = _store(
        tmp_path,
        minimum_free_disk_reserve_bytes=100,
        disk_usage=lambda _path: SimpleNamespace(free=len(serialized) + 99),
    )

    with pytest.raises(ConfluenceRawPageStoreError) as exc_info:
        store.publish_page(envelope=_envelope())

    assert exc_info.value.category.value == "raw_publication_failure"
    assert not store.resolve_page_path(run_id=RUN_ID, page_id="1000").exists()


def test_replay_remains_available_after_budget_is_full(tmp_path: Path) -> None:
    serialized = _envelope().to_bytes()
    store = _store(tmp_path, max_total_bytes=len(serialized))

    first = store.publish_page(envelope=_envelope())
    second = store.publish_page(envelope=_envelope())

    assert first.outcome is ConfluenceRawPagePublicationOutcome.PUBLISHED
    assert second.outcome is ConfluenceRawPagePublicationOutcome.REUSED


def test_restarted_guard_replays_existing_page_without_disk_budget_check(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    serialized = envelope.to_bytes()
    ConfluenceRawPageGenerationStore(raw_root=tmp_path).publish_page(
        envelope=envelope
    )
    store = _store(
        tmp_path,
        max_total_bytes=len(serialized),
        minimum_free_disk_reserve_bytes=100,
        disk_usage=lambda _path: (_ for _ in ()).throw(
            AssertionError("replay must not consume publication disk budget")
        ),
    )

    replayed = store.publish_page(envelope=envelope)

    assert replayed.outcome is ConfluenceRawPagePublicationOutcome.REUSED


def test_two_store_instances_cannot_race_the_same_budget_critical_section(
    tmp_path: Path,
) -> None:
    entered, release = Event(), Event()
    guard_lock = Lock()

    @contextmanager
    def guard():
        if not guard_lock.acquire(blocking=False):
            raise RuntimeError("writer lease unavailable")
        try:
            yield
        finally:
            guard_lock.release()

    concrete = ConfluenceRawPageGenerationStore(raw_root=tmp_path)

    class BlockingInner:
        def resolve_page_path(self, **kwargs):
            return concrete.resolve_page_path(**kwargs)

        def read_page(self, **kwargs):
            return concrete.read_page(**kwargs)

        def publish_page(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return concrete.publish_page(**kwargs)

    first = BudgetedConfluenceRawPageStore(
        inner=BlockingInner(),
        raw_root=tmp_path,
        publication_guard=guard,
        max_total_bytes=1024 * 1024,
        minimum_free_disk_reserve_bytes=0,
    )
    second = _store(tmp_path, guard_lock=guard_lock)
    failures: list[BaseException] = []

    def publish_first() -> None:
        try:
            first.publish_page(envelope=_envelope())
        except BaseException as error:  # pragma: no cover - assertion aid
            failures.append(error)

    worker = Thread(target=publish_first)
    worker.start()
    assert entered.wait(5)
    try:
        with pytest.raises(ConfluenceRawPageStoreError):
            second.publish_page(envelope=_envelope())
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    assert failures == []


def test_restarted_store_remeasures_bytes_published_by_prior_store(tmp_path: Path) -> None:
    first = _store(tmp_path)
    first.publish_page(envelope=_envelope())
    second_envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID, page_id="1001", source_version="v1",
        http_status=200, body_bytes=b"second",
    )
    total = len(_envelope().to_bytes()) + len(second_envelope.to_bytes()) - 1
    second = _store(tmp_path, max_total_bytes=total)

    with pytest.raises(ConfluenceRawPageStoreError):
        second.publish_page(envelope=second_envelope)


def test_restarted_store_publishes_new_page_when_remeasured_total_fits(
    tmp_path: Path,
) -> None:
    _store(tmp_path).publish_page(envelope=_envelope())
    second_envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID, page_id="1001", source_version="v1",
        http_status=200, body_bytes=b"second",
    )
    total = len(_envelope().to_bytes()) + len(second_envelope.to_bytes())

    artifact = _store(tmp_path, max_total_bytes=total).publish_page(
        envelope=second_envelope
    )

    assert artifact.outcome is ConfluenceRawPagePublicationOutcome.PUBLISHED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_total_bytes": 0},
        {"max_total_bytes": True},
        {"minimum_free_disk_reserve_bytes": -1},
        {"minimum_free_disk_reserve_bytes": True},
        {"disk_usage": None},
    ],
)
def test_store_rejects_invalid_budget_configuration(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _store(tmp_path, **kwargs)
