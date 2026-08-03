from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunSelectionFailure,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
    StartNewRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointStateError,
)


PROFILE = {
    "profile_id": "m7-crawl-reliability-v1",
    "profile_version": "1",
    "inventory_page_size": 50,
    "attachment_page_size": 50,
    "minimum_request_interval_seconds": 3.0,
    "max_response_bytes_per_request": 8388608,
    "max_total_requests_per_run": 50000,
    "max_attempts": 4,
    "base_backoff_seconds": 1.0,
    "max_retry_delay_seconds": 120.0,
    "max_total_retry_delay_seconds": 300.0,
    "jitter": False,
    "max_include_roots": 16,
    "max_pages_per_run": 10000,
    "max_inventory_windows_per_root": 1000,
    "max_inventory_windows_per_run": 4000,
    "max_restriction_targets_per_page": 256,
    "max_restriction_observations_per_run": 25000,
    "max_attachment_windows_per_page": 100,
    "max_attachment_windows_per_run": 10000,
    "max_raw_bytes_per_run": 34359738368,
    "max_raw_artifacts_per_run": 250000,
    "minimum_free_disk_reserve_bytes": 8589934592,
}


def _source_config() -> ConfluenceSourceConfig:
    return ConfluenceSourceConfig(
        "source",
        "SPACE",
        (ConfluenceIncludeRoot("root"),),
    )


def _start_request(workspace: Path) -> StartNewRunRequest:
    return StartNewRunRequest(
        workspace,
        "https://example.invalid/confluence",
        _source_config(),
        PROFILE,
    )


def test_public_run_port_has_method_oriented_shape_and_safe_reprs(tmp_path) -> None:
    port = SqliteConfluenceCheckpointRunPort()
    public_methods = {
        name for name in dir(port) if not name.startswith("_")
    }
    assert public_methods == {
        "start_new_run",
        "resume_explicit_run_id",
        "resume_unique_incomplete_run",
    }

    request = _start_request(tmp_path)
    assert repr(request) == "StartNewRunRequest()"
    assert "example.invalid" not in repr(request)
    assert "SPACE" not in repr(request)
    assert repr(
        ResumeExplicitRunRequest(
            tmp_path,
            CrawlRunId("123e4567-e89b-42d3-a456-426614174000"),
            request.endpoint_url,
            request.source_config,
            request.reliability_profile,
        )
    ) == "ResumeExplicitRunRequest()"
    assert repr(
        ResumeUniqueIncompleteRunRequest(
            tmp_path,
            request.endpoint_url,
            request.source_config,
            request.reliability_profile,
        )
    ) == "ResumeUniqueIncompleteRunRequest()"

    with port.start_new_run(request) as outcome:
        assert repr(outcome) == "CheckpointRunActivation()"
        public_activation_methods = {
            name for name in dir(outcome) if not name.startswith("_")
        }
        assert public_activation_methods == {
            "check_outbound_attempt",
            "commit_inventory_window",
            "commit_root_occurrence",
            "load_next_inventory_work",
            "read_schema_state",
            "reserve_outbound_attempt",
            "replay_raw_page",
            "replay_raw_restriction",
            "session_id",
            "snapshot",
                "stream_inventory_occurrences",
                "complete_session",
                "pause_session",
            }
        assert not hasattr(outcome, "_mutate")
        assert not hasattr(outcome, "_inner")
        assert not hasattr(outcome, "_workspace")


def test_public_run_port_rejects_stale_activation_after_context_exit(tmp_path) -> None:
    port = SqliteConfluenceCheckpointRunPort()
    with port.start_new_run(_start_request(tmp_path)) as outcome:
        retained = outcome

    with pytest.raises(CheckpointStateError):
        retained.read_schema_state()


def test_public_run_port_maps_selection_failures_to_typed_outcomes(tmp_path) -> None:
    port = SqliteConfluenceCheckpointRunPort()
    request = ResumeUniqueIncompleteRunRequest(
        tmp_path,
        "https://example.invalid/confluence",
        _source_config(),
        PROFILE,
    )
    with port.resume_unique_incomplete_run(request) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_not_found"


def test_public_run_request_snapshots_profile_and_rejects_invalid_shapes(tmp_path) -> None:
    profile = dict(PROFILE)
    request = StartNewRunRequest(
        tmp_path, "https://example.invalid/confluence", _source_config(), profile
    )
    profile["max_attempts"] = 99
    assert request.reliability_profile["max_attempts"] == 4
    with pytest.raises(TypeError):
        StartNewRunRequest(tmp_path, "https://example.invalid", _source_config(), None)
    with pytest.raises(ValueError):
        StartNewRunRequest(tmp_path, "", _source_config(), PROFILE)
    with pytest.raises(TypeError):
        StartNewRunRequest(tmp_path, "https://example.invalid", object(), PROFILE)
    with pytest.raises(ValueError):
        StartNewRunRequest(
            tmp_path,
            "https://example.invalid",
            _source_config(),
            {**PROFILE, "max_attempts": 99},
        )
    port = SqliteConfluenceCheckpointRunPort()
    with port.start_new_run(
        ResumeUniqueIncompleteRunRequest(
            tmp_path,
            "https://example.invalid/confluence",
            _source_config(),
            PROFILE,
        )
    ) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_operation_invalid"
