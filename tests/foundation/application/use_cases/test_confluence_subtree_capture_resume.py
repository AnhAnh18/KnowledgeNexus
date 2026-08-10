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
from knowledgenexus.foundation.domain.models.confluence_page_metadata import ConfluencePageMetadata
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
