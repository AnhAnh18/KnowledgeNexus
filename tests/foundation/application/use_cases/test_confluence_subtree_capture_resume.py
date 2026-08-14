import hashlib
import json

import pytest

from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import (
    CaptureConfluenceSubtreePages,
    PAGE_CAPTURE_FAILURE_CATEGORIES,
    PageCaptureResult,
)
from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_raw_page_generation import (
    GenerationRawPageFetchError,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CanonicalIncludeRoots,
    CrawlRunId,
    InventoryRootCommit,
)
from knowledgenexus.foundation.domain.models.confluence_inventory_occurrence import (
    InventoryOccurrence,
)
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageArtifact,
    ConfluenceRawPagePublicationOutcome,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    RawPageReplayDecision,
    RawPageReplayFailure,
    RawPageReplayFailureCategory,
    RawPageReplayResult,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import ConfluencePageFetchError


def test_capture_result_requires_exact_selected_total_for_completion():
    result = PageCaptureResult(100, 0, 0, 0, False, 100)
    assert result.complete is True
    incomplete = PageCaptureResult(
        99, 0, 0, 1, True, 100, (("fetch_http", 1),)
    )
    assert incomplete.complete is False


def test_capture_result_rejects_impossible_counter_sum():
    with pytest.raises(ValueError):
        PageCaptureResult(101, 0, 0, 0, False, 100)

    with pytest.raises(ValueError, match="non-stopped"):
        PageCaptureResult(99, 0, 0, 0, False, 100)

    with pytest.raises(ValueError, match="non-stopped"):
        PageCaptureResult(
            99, 0, 0, 1, False, 100, (("fetch_http", 1),)
        )


@pytest.mark.parametrize(
    "categories",
    [
        (("fetch_http", 2),),
        (("unknown", 1),),
        (("fetch_http", True),),
        (("fetch_store", 1), ("fetch_http", 1)),
        [("fetch_http", 1)],
        (object(),),
    ],
)
def test_capture_result_rejects_malformed_failure_aggregates(categories):
    with pytest.raises((TypeError, ValueError)):
        PageCaptureResult(0, 0, 0, 1, True, 1, categories)


def test_page_capture_failure_vocabulary_is_closed_and_sanitized():
    assert "fetch_http" in PAGE_CAPTURE_FAILURE_CATEGORIES
    assert "replay_inspection_failed" in PAGE_CAPTURE_FAILURE_CATEGORIES
    assert "acknowledgement_identity_conflict" in PAGE_CAPTURE_FAILURE_CATEGORIES
    assert all(
        category == category.lower()
        and category.replace("_", "").isalnum()
        and not any(character.isspace() for character in category)
        for category in PAGE_CAPTURE_FAILURE_CATEGORIES
    )


def test_zero_batch_stop_does_not_consume_pages():
    # The use case's zero-limit path is represented by the typed result contract.
    result = PageCaptureResult(0, 0, 0, 0, True, 200)
    assert result.complete is False
    assert result.captured + result.replayed + result.skipped + result.failed == 0


def test_root_inventory_fact_is_included_in_page_capture():
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="7"),
        CanonicalIncludeRoots(("1000",)),
    )

    class State:
        def replay_raw_page(self, _command, _inspector):
            return RawPageReplayResult(RawPageReplayDecision.REPLAYED, True)

        def acknowledge_raw_page(self, _acknowledgement):
            raise AssertionError("a replayed root must not be captured again")

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns the replay decision")

    class Store:
        def read_page(self, **_kwargs):
            raise AssertionError("a replayed root must not be read")

        def publish_page(self, **_kwargs):
            raise AssertionError("a replayed root must not be written")

    class Fetcher:
        def fetch_page_raw(self, _page_id):
            raise AssertionError("a replayed root must not be fetched")

    result = CaptureConfluenceSubtreePages(
        state_session=State(), orphan_inspector=Inspector(),
        page_fetcher=Fetcher(), raw_page_store=Store(),
    ).run(run_id=run_id, occurrences=(root,))

    assert result.replayed == 1
    assert result.expected_total == 1
    assert result.complete is True


def test_capture_rejects_inventory_above_bound_before_replay():
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    roots = CanonicalIncludeRoots(("1000",))
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        roots,
    )
    child = InventoryOccurrence(
        run_id,
        0,
        "1000",
        0,
        0,
        "1001",
        ConfluencePageMetadata(
            "1001",
            "Child",
            "SPACE",
            parent_page_id="1000",
            ancestor_page_ids=("1000",),
            ancestor_titles=("Root",),
            source_version="1",
        ),
        roots,
    )

    class State:
        def replay_raw_page(self, *_args):
            raise AssertionError("page-bound failure must precede replay")

        def acknowledge_raw_page(self, *_args):
            raise AssertionError("page-bound failure must precede acknowledgement")

    class Inspector:
        def inspect_raw_page(self, *_args):
            raise AssertionError("page-bound failure must precede inspection")

    class Store:
        def read_page(self, **_kwargs):
            raise AssertionError("page-bound failure must precede raw reads")

        def publish_page(self, **_kwargs):
            raise AssertionError("page-bound failure must precede raw writes")

    class Fetcher:
        def fetch_page_raw(self, **_kwargs):
            raise AssertionError("page-bound failure must precede fetch")

    use_case = CaptureConfluenceSubtreePages(
        state_session=State(),
        orphan_inspector=Inspector(),
        page_fetcher=Fetcher(),
        raw_page_store=Store(),
        max_pages=1,
    )

    with pytest.raises(ValueError, match="page budget"):
        use_case.run(run_id=run_id, occurrences=(root, child))


def test_two_batch_controlled_stop_resumes_without_refetching_committed_pages(tmp_path):
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    roots = CanonicalIncludeRoots(("1000",))
    root = InventoryRootCommit(
        run_id, 0, "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        roots,
    )
    descendants = tuple(
        InventoryOccurrence(
            run_id, 0, "1000", 0, ordinal, page_id,
            ConfluencePageMetadata(
                page_id, f"Page {page_id}", "SPACE", parent_page_id="1000",
                ancestor_page_ids=("1000",), ancestor_titles=("Root",),
                source_version="1",
            ),
            roots,
        )
        for ordinal, page_id in enumerate(str(value) for value in range(1001, 1201))
    )
    occurrences = (root, *descendants)

    class State:
        def __init__(self) -> None:
            self.committed: set[str] = set()

        def replay_raw_page(self, command, _inspector):
            page_id = command.request.page_id
            decision = (
                RawPageReplayDecision.COMMITTED
                if page_id in self.committed
                else RawPageReplayDecision.MISSING
            )
            return RawPageReplayResult(decision)

        def acknowledge_raw_page(self, acknowledgement):
            self.committed.add(acknowledgement.envelope.page_id)
            return RawPageReplayResult(RawPageReplayDecision.COMMITTED)

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns replay decisions")

    class Fetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch_page_raw(self, page_id):
            self.calls.append(page_id)
            return json.dumps({"id": page_id, "version": {"number": 1}}).encode()

    class Store:
        def __init__(self) -> None:
            self.envelopes = {}

        def publish_page(self, *, envelope):
            self.envelopes[envelope.page_id] = envelope
            serialized = envelope.to_bytes()
            return ConfluenceRawPageArtifact(
                path=(tmp_path / f"{envelope.page_id}.json").resolve(),
                run_id=envelope.run_id,
                page_id=envelope.page_id,
                raw_sha256=hashlib.sha256(serialized).hexdigest(),
                byte_count=len(serialized),
                outcome=ConfluenceRawPagePublicationOutcome.PUBLISHED,
            )

        def read_page(self, *, run_id, page_id):
            envelope = self.envelopes[page_id]
            assert envelope.run_id == run_id
            return envelope

    state = State()
    fetcher = Fetcher()
    use_case = CaptureConfluenceSubtreePages(
        state_session=state,
        orphan_inspector=Inspector(),
        page_fetcher=fetcher,
        raw_page_store=Store(),
    )

    stopped = use_case.run(
        run_id=run_id, occurrences=occurrences, stop_after_batches=2
    )
    assert stopped.stopped is True
    assert stopped.captured == 200
    assert len(fetcher.calls) == 200

    resumed = use_case.run(run_id=run_id, occurrences=occurrences)
    assert resumed.complete is True
    assert resumed.replayed == 200
    assert resumed.captured == 1
    assert len(fetcher.calls) == 201
    assert len(set(fetcher.calls)) == 201


def test_mixed_batch_reports_sanitized_failures_and_replays_committed_pages(tmp_path):
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    roots = CanonicalIncludeRoots(("1000",))
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        roots,
    )
    descendants = tuple(
        InventoryOccurrence(
            run_id,
            0,
            "1000",
            0,
            ordinal,
            page_id,
            ConfluencePageMetadata(
                page_id,
                "Child",
                "SPACE",
                parent_page_id="1000",
                ancestor_page_ids=("1000",),
                ancestor_titles=("Root",),
                source_version="1",
            ),
            roots,
        )
        for ordinal, page_id in enumerate(
            (str(value) for value in range(1001, 1100))
        )
    )
    occurrences = (root, *descendants)

    class State:
        def __init__(self) -> None:
            self.committed: set[str] = set()

        def replay_raw_page(self, command, _inspector):
            decision = (
                RawPageReplayDecision.COMMITTED
                if command.request.page_id in self.committed
                else RawPageReplayDecision.MISSING
            )
            return RawPageReplayResult(decision)

        def acknowledge_raw_page(self, acknowledgement):
            self.committed.add(acknowledgement.envelope.page_id)
            return RawPageReplayResult(RawPageReplayDecision.COMMITTED)

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns replay decisions")

    class Fetcher:
        def __init__(self) -> None:
            self.fail_last_six = True
            self.calls: list[str] = []

        def fetch_page_raw(self, *, page_id):
            self.calls.append(page_id)
            if self.fail_last_six and len(self.calls) > 94:
                raise ConfluencePageFetchError()
            return json.dumps({"id": page_id, "version": {"number": 1}}).encode()

    class Store:
        def __init__(self) -> None:
            self.envelopes = {}

        def publish_page(self, *, envelope):
            self.envelopes[envelope.page_id] = envelope
            serialized = envelope.to_bytes()
            return ConfluenceRawPageArtifact(
                path=(tmp_path / f"{envelope.page_id}.json").resolve(),
                run_id=envelope.run_id,
                page_id=envelope.page_id,
                raw_sha256=hashlib.sha256(serialized).hexdigest(),
                byte_count=len(serialized),
                outcome=ConfluenceRawPagePublicationOutcome.PUBLISHED,
            )

        def read_page(self, *, run_id, page_id):
            envelope = self.envelopes[page_id]
            assert envelope.run_id == run_id
            return envelope

    state = State()
    fetcher = Fetcher()
    use_case = CaptureConfluenceSubtreePages(
        state_session=state,
        orphan_inspector=Inspector(),
        page_fetcher=fetcher,
        raw_page_store=Store(),
    )

    stopped = use_case.run(run_id=run_id, occurrences=occurrences)

    assert stopped.stopped is True
    assert stopped.captured == 94
    assert stopped.failed == 6
    assert stopped.failure_categories == (("fetch_http", 6),)
    assert len(state.committed) == 94

    fetcher.fail_last_six = False
    resumed = use_case.run(run_id=run_id, occurrences=occurrences)

    assert resumed.complete is True
    assert resumed.replayed == 94
    assert resumed.captured == 6
    assert resumed.failure_categories == ()
    assert len(fetcher.calls) == 106


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (
            RawPageReplayFailure(RawPageReplayFailureCategory.INSPECTION_FAILED),
            "replay_inspection_failed",
        ),
        (RawPageReplayResult(RawPageReplayDecision.CONFLICT), "replay_conflict"),
        (object(), "replay_result_invalid"),
        (None, "replay_result_invalid"),
    ],
)
def test_replay_boundary_failures_are_sanitized_before_field_access(
    outcome, expected
):
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        CanonicalIncludeRoots(("1000",)),
    )

    class State:
        def replay_raw_page(self, _command, _inspector):
            return outcome

        def acknowledge_raw_page(self, _acknowledgement):
            raise AssertionError("a replay failure must precede acknowledgement")

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns replay decisions")

    class Store:
        def read_page(self, **_kwargs):
            raise AssertionError("a replay failure must precede raw reads")

        def publish_page(self, **_kwargs):
            raise AssertionError("a replay failure must precede raw writes")

    class Fetcher:
        def fetch_page_raw(self, **_kwargs):
            raise AssertionError("a replay failure must precede fetch")

    result = CaptureConfluenceSubtreePages(
        state_session=State(),
        orphan_inspector=Inspector(),
        page_fetcher=Fetcher(),
        raw_page_store=Store(),
    ).run(run_id=run_id, occurrences=(root,))

    assert result.failed == 1
    assert result.failure_categories == ((expected, 1),)


@pytest.mark.parametrize(
    ("acknowledgement", "expected"),
    [
        (
            RawPageReplayFailure(RawPageReplayFailureCategory.INVALID_REQUEST),
            "acknowledgement_invalid_request",
        ),
        (
            RawPageReplayResult(RawPageReplayDecision.IDENTITY_CONFLICT),
            "acknowledgement_identity_conflict",
        ),
        (object(), "acknowledgement_result_invalid"),
        (None, "acknowledgement_result_invalid"),
    ],
)
def test_acknowledgement_boundary_failures_are_sanitized_before_field_access(
    acknowledgement, expected, tmp_path
):
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        CanonicalIncludeRoots(("1000",)),
    )

    class State:
        def replay_raw_page(self, _command, _inspector):
            return RawPageReplayResult(RawPageReplayDecision.MISSING)

        def acknowledge_raw_page(self, _acknowledgement):
            return acknowledgement

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns replay decisions")

    class Fetcher:
        def fetch_page_raw(self, *, page_id):
            return json.dumps({"id": page_id, "version": {"number": 1}}).encode()

    class Store:
        def publish_page(self, *, envelope):
            self.envelope = envelope
            serialized = envelope.to_bytes()
            return ConfluenceRawPageArtifact(
                path=(tmp_path / "page.json").resolve(),
                run_id=envelope.run_id,
                page_id=envelope.page_id,
                raw_sha256=hashlib.sha256(serialized).hexdigest(),
                byte_count=len(serialized),
                outcome=ConfluenceRawPagePublicationOutcome.PUBLISHED,
            )

        def read_page(self, *, run_id, page_id):
            assert self.envelope.run_id == run_id
            assert self.envelope.page_id == page_id
            return self.envelope

    result = CaptureConfluenceSubtreePages(
        state_session=State(),
        orphan_inspector=Inspector(),
        page_fetcher=Fetcher(),
        raw_page_store=Store(),
    ).run(run_id=run_id, occurrences=(root,))

    assert result.failed == 1
    assert result.failure_categories == ((expected, 1),)


def test_unknown_fetch_error_category_fails_closed_without_falsifying_http(tmp_path):
    run_id = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
    root = InventoryRootCommit(
        run_id,
        0,
        "1000",
        ConfluencePageMetadata("1000", "Root", "SPACE", source_version="1"),
        CanonicalIncludeRoots(("1000",)),
    )

    class State:
        def replay_raw_page(self, _command, _inspector):
            return RawPageReplayResult(RawPageReplayDecision.MISSING)

        def acknowledge_raw_page(self, _acknowledgement):
            raise AssertionError("fetch failure must precede acknowledgement")

    class Inspector:
        def inspect_raw_page(self, _request):
            raise AssertionError("the state fake owns replay decisions")

    class Fetcher:
        def fetch_page_raw(self, *, page_id):
            raise AssertionError("the injected fetch seam is used instead")

    class Store:
        def read_page(self, **_kwargs):
            raise AssertionError("fetch failure must precede raw reads")

        def publish_page(self, **_kwargs):
            raise AssertionError("fetch failure must precede raw writes")

    use_case = CaptureConfluenceSubtreePages(
        state_session=State(),
        orphan_inspector=Inspector(),
        page_fetcher=Fetcher(),
        raw_page_store=Store(),
    )

    class InvalidFetch:
        def execute(self, **_kwargs):
            raise GenerationRawPageFetchError("future_unapproved_category")

    use_case._fetch = InvalidFetch()
    result = use_case.run(run_id=run_id, occurrences=(root,))

    assert result.failed == 1
    assert result.failure_categories == (("fetch_failure_invalid", 1),)
