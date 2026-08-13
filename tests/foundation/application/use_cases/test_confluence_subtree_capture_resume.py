import hashlib
import json

import pytest

from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import (
    CaptureConfluenceSubtreePages,
    PageCaptureResult,
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
    RawPageReplayResult,
)


def test_capture_result_requires_exact_selected_total_for_completion():
    result = PageCaptureResult(100, 0, 0, 0, False, 100)
    assert result.complete is True
    incomplete = PageCaptureResult(99, 0, 0, 1, True, 100)
    assert incomplete.complete is False


def test_capture_result_rejects_impossible_counter_sum():
    with pytest.raises(ValueError):
        PageCaptureResult(101, 0, 0, 0, False, 100)


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
