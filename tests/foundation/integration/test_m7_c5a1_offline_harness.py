"""C5-A1 focused entry point; implementation helpers remain shared."""

from test_m7_c5a_offline_harness import (
    test_c5a1_controlled_stop_persists_pause_and_resumes as _pause,
    test_c5a1_session_finalizers_reject_stale_activation_without_mutation as _stale,
    test_c5a_selection_failures_are_typed_and_nonmutating as _selection,
    test_c5a_uninterrupted_and_after_response_resume_have_same_durable_rows as _replay,
)


def test_c5a1_replay(tmp_path):
    return _replay(tmp_path)


def test_c5a1_controlled_stop(tmp_path):
    return _pause(tmp_path)


def test_c5a1_stale_finalizer(tmp_path):
    return _stale(tmp_path)


def test_c5a1_selection(tmp_path):
    return _selection(tmp_path)
