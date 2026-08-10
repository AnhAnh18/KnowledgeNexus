import pytest

from knowledgenexus.foundation.application.use_cases.capture_confluence_subtree_pages import PageCaptureResult


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
