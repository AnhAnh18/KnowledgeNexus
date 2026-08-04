from __future__ import annotations

import sqlite3
from dataclasses import replace

from test_m7_c5a_offline_harness import PROFILE, _request

from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_port import (
    SqliteConfluenceCheckpointRunPort,
)
from knowledgenexus.foundation.infrastructure.checkpoint.sqlite_checkpoint_run_registry import (
    _RunRegistryRequest,
    _register_checkpoint_run,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_run_port import (
    CheckpointRunSelectionFailure,
    ResumeExplicitRunRequest,
    ResumeUniqueIncompleteRunRequest,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import StartNewRun


def test_unique_resume_on_fresh_workspace_has_no_database_mutation(tmp_path):
    workspace = tmp_path / "fresh"
    workspace.mkdir()
    request = _request(workspace, ResumeUniqueIncompleteRunRequest)
    with SqliteConfluenceCheckpointRunPort().resume_unique_incomplete_run(request) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_not_found"
    assert not (workspace / "crawl_state.sqlite3").exists()


def test_start_conflict_after_prior_activation_closes(tmp_path):
    workspace = tmp_path / "conflict"
    workspace.mkdir()
    port = SqliteConfluenceCheckpointRunPort()
    request = _request(workspace)
    with port.start_new_run(request) as first:
        run_id = first.snapshot.run_id
        first.pause_session()
    with port.start_new_run(request) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "incomplete_run_conflict"
    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM crawl_runs").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM crawl_sessions").fetchone() == (1,)
    assert run_id.value


def test_explicit_resume_mismatch_is_not_resumable(tmp_path):
    workspace = tmp_path / "mismatch"
    workspace.mkdir()
    port = SqliteConfluenceCheckpointRunPort()
    request = _request(workspace)
    with port.start_new_run(request) as first:
        run_id = first.snapshot.run_id
    wrong = _request(workspace, ResumeExplicitRunRequest, run_id)
    wrong = replace(wrong, source_config=wrong.source_config.__class__(
        wrong.source_config.source_id,
        "OTHER",
        wrong.source_config.include_roots,
        page_size=50,
    ))
    with port.resume_explicit_run_id(wrong) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_not_resumable"

    wrong_root = request.source_config.__class__(
            request.source_config.source_id,
            request.source_config.space_key,
            (request.source_config.include_roots[0].__class__("9999"),),
            page_size=request.source_config.page_size,
        )
    with port.resume_explicit_run_id(replace(wrong, source_config=wrong_root)) as outcome:
        assert isinstance(outcome, CheckpointRunSelectionFailure)
        assert outcome.category == "run_not_resumable"

    with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM crawl_sessions").fetchone() == (1,)


def test_request_budget_denial_is_before_any_transport_attempt(tmp_path):
    workspace = tmp_path / "budget"
    workspace.mkdir()
    request = _request(workspace)
    with _register_checkpoint_run(
        _RunRegistryRequest(
            request.workspace,
            StartNewRun(),
            request.endpoint_url,
            request.source_config,
            request.reliability_profile,
        )
    ) as activation:
        activation._state._limits = replace(
            activation._state._limits, max_total_requests_per_run=0
        )
        with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
            before = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("request_budget_reservations", "inventory_windows", "inventory_occurrences", "crawl_sessions")
            }
        denied = activation.reserve_outbound_attempt()
        assert isinstance(denied, CheckpointOperationFailure)
        assert denied.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED
        assert activation.load_next_inventory_work() is not None
        with sqlite3.connect(workspace / "crawl_state.sqlite3") as db:
            after = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }
        assert after == before
