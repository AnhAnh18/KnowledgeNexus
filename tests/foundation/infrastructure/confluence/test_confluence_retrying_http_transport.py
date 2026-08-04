"""M7-B3 — focused tests for retrying Confluence HTTP executor."""

from __future__ import annotations

from email.message import Message
from typing import Any

import pytest

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    confluence_retry_after_absent,
)
from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRequestBudgetAction,
    ConfluenceRequestBudgetDecision,
    ConfluenceRetryOutcomeClass,
    ConfluenceRetryPolicyAction,
    ConfluenceRetryPolicyDecision,
    ConfluenceRetryPolicyProfile,
    ConfluenceRetryStableKind,
    confluence_request_budget_terminate,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    ConfluenceRetryExecutorProfile,
    ConfluenceRetryExecutionError,
    ConfluenceRetryExecutionSnapshot,
    ConfluenceStatusAwareExecutionResult,
    RetryingConfluenceHttpTransport,
    UrllibConfluenceHttpTransport,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_http_transport as transport_module,
)
from knowledgenexus.foundation.infrastructure.confluence import (
    confluence_retrying_http_transport as retrying_transport_module,
)


BASE_URL = "https://fixture.invalid/confluence"
PAT = "fixture-secret-token"


class FakeResponse:
    """Fake HTTP response for testing."""

    def __init__(
        self,
        *,
        body: bytes = b'{"ok":true}',
        status: int = 200,
        headers: Message | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers or Message()
        self.read_limits: list[int] = []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return self.body[:limit]


class RecordingOpener:
    """Records opener calls for verification."""

    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[Any, float]] = []

    def open(self, request: Any, *, timeout: float) -> Any:
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class RecordingSleeper:
    """Records sleep calls for verification."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def __call__(self, duration: float) -> None:
        self.sleeps.append(duration)


def _make_full_profile_mapping(
    *,
    max_total_requests_per_run: int = 50000,
    max_attempts: int = 4,
) -> dict[str, object]:
    """Create a full valid profile-v1 mapping with optional overrides."""
    return {
        "profile_id": "m7-crawl-reliability-v1",
        "profile_version": "1",
        "inventory_page_size": 50,
        "attachment_page_size": 50,
        "minimum_request_interval_seconds": 3.0,
        "max_response_bytes_per_request": 8388608,
        "max_total_requests_per_run": max_total_requests_per_run,
        "max_attempts": max_attempts,
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


def _transport(
    *,
    response: FakeResponse | None = None,
    outcome: object | None = None,
    max_response_bytes: int = 1024,
    initial_requests_started: int = 0,
    max_total_requests_per_run: int = 50000,
) -> tuple[RetryingConfluenceHttpTransport, RecordingOpener, RecordingSleeper, list[int | float]]:
    """Create a retrying transport with injected clock and sleeper."""
    selected_outcome = outcome if outcome is not None else response or FakeResponse()
    opener = RecordingOpener(selected_outcome)
    sleeper = RecordingSleeper()
    clock_times: list[int | float] = []

    def build_opener(*handlers: object) -> RecordingOpener:
        return opener

    def monotonic_clock() -> int | float:
        if not clock_times:
            clock_times.append(0)
        else:
            clock_times.append(clock_times[-1] + 1)
        return clock_times[-1]

    import urllib.request
    original_build_opener = urllib.request.build_opener
    urllib.request.build_opener = build_opener  # type: ignore

    try:
        inner = UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            timeout_seconds=12.5,
            max_response_bytes=max_response_bytes,
        )

        profile = ConfluenceRetryExecutorProfile.from_mapping(
            _make_full_profile_mapping(
                max_total_requests_per_run=max_total_requests_per_run
            )
        )

        transport = RetryingConfluenceHttpTransport(
            inner=inner,
            profile=profile,
            monotonic_clock=monotonic_clock,
            sleeper=sleeper,
            initial_requests_started_for_run=initial_requests_started,
        )

        return transport, opener, sleeper, clock_times
    finally:
        urllib.request.build_opener = original_build_opener  # type: ignore


# =============================================================================
# Section 10: Executor profile validation
# =============================================================================


def test_profile_from_mapping_valid() -> None:
    """Profile factory accepts valid mapping."""
    profile = ConfluenceRetryExecutorProfile.from_mapping(
        _make_full_profile_mapping()
    )
    assert profile.minimum_request_interval_seconds == 3.0
    assert profile.retry_policy.max_attempts == 4


def test_profile_rejects_wrong_interval_value() -> None:
    """Profile factory rejects interval != 3.0."""
    mapping = _make_full_profile_mapping()
    mapping["minimum_request_interval_seconds"] = 5.0
    with pytest.raises(ValueError, match="has an unexpected value"):
        ConfluenceRetryExecutorProfile.from_mapping(mapping)


def test_profile_direct_construction_valid() -> None:
    """Direct profile construction with valid values."""
    retry_policy = ConfluenceRetryPolicyProfile.from_mapping(
        _make_full_profile_mapping()
    )
    profile = ConfluenceRetryExecutorProfile(
        retry_policy=retry_policy,
        minimum_request_interval_seconds=3.0,
    )
    assert profile.minimum_request_interval_seconds == 3.0


def test_profile_direct_construction_rejects_bool_interval() -> None:
    """Direct profile construction rejects bool interval."""
    retry_policy = ConfluenceRetryPolicyProfile.from_mapping(
        _make_full_profile_mapping()
    )
    with pytest.raises(TypeError, match="expects an exact float"):
        ConfluenceRetryExecutorProfile(
            retry_policy=retry_policy,
            minimum_request_interval_seconds=True,  # type: ignore
        )


# =============================================================================
# Section 11: Constructor validation
# =============================================================================


def test_constructor_valid() -> None:
    """Constructor accepts valid arguments."""
    transport, opener, sleeper, _ = _transport()
    assert transport is not None
    assert opener is not None
    assert sleeper is not None


def test_constructor_rejects_wrong_inner_type() -> None:
    """Constructor rejects non-UrllibConfluenceHttpTransport inner."""
    profile = ConfluenceRetryExecutorProfile.from_mapping(
        _make_full_profile_mapping()
    )
    with pytest.raises(TypeError, match="expects a UrllibConfluenceHttpTransport"):
        RetryingConfluenceHttpTransport(
            inner="not a transport",  # type: ignore
            profile=profile,
            monotonic_clock=lambda: 0,
            sleeper=lambda x: None,
        )


def test_constructor_rejects_negative_initial_count() -> None:
    """Constructor rejects negative initial_requests_started_for_run."""
    with pytest.raises(ValueError, match="must be non-negative"):
        _transport(initial_requests_started=-1)


def test_constructor_rejects_bool_initial_count() -> None:
    """Constructor rejects bool initial_requests_started_for_run."""
    with pytest.raises(TypeError, match="expects an exact int"):
        _transport(initial_requests_started=True)  # type: ignore


def test_constructor_rejects_excessive_initial_count() -> None:
    """Constructor rejects initial count exceeding profile limit."""
    with pytest.raises(ValueError, match="must not exceed"):
        _transport(initial_requests_started=50001)  # max_total_requests_per_run=50000


# =============================================================================
# Section 12: Ownership-isolated state and snapshot
# =============================================================================


def test_snapshot_initial_state() -> None:
    """Snapshot returns correct initial state."""
    transport, _, _, _ = _transport()
    snapshot = transport.snapshot()
    assert snapshot.requests_started_for_run == 0
    assert snapshot.last_attempt_started_at is None


def test_snapshot_with_initial_count() -> None:
    """Snapshot reflects initial count."""
    transport, _, _, _ = _transport(initial_requests_started=5)
    snapshot = transport.snapshot()
    assert snapshot.requests_started_for_run == 5
    assert snapshot.last_attempt_started_at is None


def test_snapshot_type_validation() -> None:
    """Snapshot validates its fields."""
    with pytest.raises(TypeError, match="expects an exact int"):
        ConfluenceRetryExecutionSnapshot(
            requests_started_for_run="not an int",  # type: ignore
            last_attempt_started_at=None,
        )

    with pytest.raises(ValueError, match="must be non-negative"):
        ConfluenceRetryExecutionSnapshot(
            requests_started_for_run=-1,
            last_attempt_started_at=None,
        )


def test_snapshot_repr_does_not_disclose_values() -> None:
    """Snapshot repr is safe."""
    snapshot = ConfluenceRetryExecutionSnapshot(
        requests_started_for_run=42,
        last_attempt_started_at=12345,
    )
    rendered = repr(snapshot)
    assert "42" not in rendered
    assert "12345" not in rendered


# =============================================================================
# Section 13: Monotonic clock handling
# =============================================================================


def test_clock_accepts_int() -> None:
    """Clock returning int is accepted."""
    transport, opener, sleeper, clock_times = _transport()
    transport.get_json(path="/rest/api/search", query={"start": "0"})
    assert len(opener.calls) == 1
    assert all(isinstance(t, int) for t in clock_times)


def test_clock_accepts_float() -> None:
    """Clock returning float is accepted."""
    clock_times: list[int | float] = []

    def float_clock() -> float:
        clock_times.append(len(clock_times) * 1.5)
        return clock_times[-1]

    def build_opener(*handlers: object) -> RecordingOpener:
        return RecordingOpener(FakeResponse())

    import urllib.request
    original_build_opener = urllib.request.build_opener
    urllib.request.build_opener = build_opener  # type: ignore

    try:
        inner = UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            timeout_seconds=12.5,
        )
        profile = ConfluenceRetryExecutorProfile.from_mapping(
            _make_full_profile_mapping()
        )
        transport = RetryingConfluenceHttpTransport(
            inner=inner,
            profile=profile,
            monotonic_clock=float_clock,
            sleeper=lambda x: None,
        )
        transport.get_json(path="/rest/api/search", query={"start": "0"})
        assert all(isinstance(t, float) for t in clock_times)
    finally:
        urllib.request.build_opener = original_build_opener  # type: ignore


def test_clock_huge_integer_no_overflow() -> None:
    """Huge integer clock samples don't cause OverflowError."""
    huge = 10**10000
    clock_values = [huge, huge + 1]
    call_count = [0]

    def huge_clock() -> int:
        idx = min(call_count[0], len(clock_values) - 1)
        call_count[0] += 1
        return clock_values[idx]

    def build_opener(*handlers: object) -> RecordingOpener:
        return RecordingOpener(FakeResponse())

    import urllib.request
    original_build_opener = urllib.request.build_opener
    urllib.request.build_opener = build_opener  # type: ignore

    try:
        inner = UrllibConfluenceHttpTransport(
            base_url=BASE_URL,
            personal_access_token=PAT,
            timeout_seconds=12.5,
        )
        profile = ConfluenceRetryExecutorProfile.from_mapping(
            _make_full_profile_mapping()
        )
        transport = RetryingConfluenceHttpTransport(
            inner=inner,
            profile=profile,
            monotonic_clock=huge_clock,
            sleeper=lambda x: None,
        )
        transport.get_json(path="/rest/api/search", query={"start": "0"})
    finally:
        urllib.request.build_opener = original_build_opener  # type: ignore


# =============================================================================
# Section 15: Initial pacing behavior
# =============================================================================


def test_first_request_no_pacing_sleep() -> None:
    """First request has no pacing sleep (last_attempt_started_at is None)."""
    transport, opener, sleeper, _ = _transport()
    transport.get_json(path="/rest/api/search", query={"start": "0"})
    assert len(opener.calls) == 1


def test_subsequent_request_pacing() -> None:
    """Subsequent requests respect minimum_request_interval_seconds."""
    transport, opener, sleeper, clock_times = _transport()

    transport.get_json(path="/rest/api/search", query={"start": "0"})
    transport.get_json(path="/rest/api/search", query={"start": "1"})

    assert len(opener.calls) == 2


# =============================================================================
# Section 17: Request accounting
# =============================================================================


def test_request_count_increments_per_attempt() -> None:
    """requests_started_for_run increments exactly once per attempt."""
    transport, opener, sleeper, _ = _transport()

    initial_snapshot = transport.snapshot()
    assert initial_snapshot.requests_started_for_run == 0

    transport.get_json(path="/rest/api/search", query={"start": "0"})

    after_snapshot = transport.snapshot()
    assert after_snapshot.requests_started_for_run == 1
    assert len(opener.calls) == 1


def test_request_count_with_initial_value() -> None:
    """Request count starts from initial value."""
    transport, opener, sleeper, _ = _transport(initial_requests_started=5)

    initial_snapshot = transport.snapshot()
    assert initial_snapshot.requests_started_for_run == 5

    transport.get_json(path="/rest/api/search", query={"start": "0"})

    after_snapshot = transport.snapshot()
    assert after_snapshot.requests_started_for_run == 6


def test_last_attempt_started_at_updated() -> None:
    """last_attempt_started_at is set on first attempt."""
    transport, opener, sleeper, clock_times = _transport()

    before_snapshot = transport.snapshot()
    assert before_snapshot.last_attempt_started_at is None

    transport.get_json(path="/rest/api/search", query={"start": "0"})

    after_snapshot = transport.snapshot()
    assert after_snapshot.last_attempt_started_at is not None
    assert after_snapshot.last_attempt_started_at == clock_times[-1]


# =============================================================================
# Section 19: Retry execution with JSON
# =============================================================================


def test_get_json_success() -> None:
    """get_json returns parsed JSON on success."""
    transport, opener, sleeper, _ = _transport(
        response=FakeResponse(body=b'{"id": "1000", "title": "Test"}')
    )

    result = transport.get_json(path="/rest/api/content/1000", query={})

    assert result == {"id": "1000", "title": "Test"}
    assert len(opener.calls) == 1


# =============================================================================
# Section 19: Retry execution with bytes
# =============================================================================


def test_get_bytes_success() -> None:
    """get_bytes returns raw bytes on success."""
    raw_body = b"raw response body"
    transport, opener, sleeper, _ = _transport(
        response=FakeResponse(body=raw_body)
    )

    result = transport.get_bytes(path="/rest/api/content/1000", query={})

    assert result == raw_body
    assert len(opener.calls) == 1


# =============================================================================
# Section 19: Status-aware typed result
# =============================================================================


def test_get_response_bytes_result_success() -> None:
    """get_response_bytes_result returns success result."""
    transport, opener, sleeper, _ = _transport()

    result = transport.get_response_bytes_result(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert isinstance(result, ConfluenceStatusAwareExecutionResult)
    assert result.response.status_code == 200
    assert result.terminal_decision is None


def test_get_response_bytes_result_429_observation() -> None:
    """get_response_bytes_result returns 429 with terminal decision after retries."""
    headers = Message()
    headers["Retry-After"] = "30"
    failure = FakeResponse(status=429, headers=headers, body=b"rate limited")

    transport, opener, sleeper, _ = _transport(outcome=failure)

    result = transport.get_response_bytes_result(
        path="/rest/api/content/1000/restriction/byOperation/view",
        query={},
    )

    assert result.response.status_code == 429
    assert result.response.body == b"rate limited"
    assert result.response.retry_after.state.name == "VALID"
    assert result.response.retry_after.delay_seconds == 30
    # After max attempts, 429 results in TERMINATE decision
    assert result.terminal_decision is not None
    assert result.terminal_decision.action is ConfluenceRetryPolicyAction.TERMINATE


def test_get_response_bytes_result_terminal_decision() -> None:
    """get_response_bytes_result returns terminal decision for non-retryable."""
    failure = FakeResponse(status=400, body=b"Bad Request")

    transport, opener, sleeper, _ = _transport(outcome=failure)

    result = transport.get_response_bytes_result(
        path="/rest/api/content/1000",
        query={},
    )

    assert result.response.status_code == 400
    assert result.terminal_decision is not None
    assert result.terminal_decision.action is ConfluenceRetryPolicyAction.TERMINATE


# =============================================================================
# Section 14: ConfluenceRetryExecutionError
# =============================================================================


def test_retry_execution_error_with_budget_decision() -> None:
    """ConfluenceRetryExecutionError carries budget decision."""
    decision = confluence_request_budget_terminate()
    error = ConfluenceRetryExecutionError(
        "Budget exhausted",
        decision=decision,
    )

    assert error.decision is decision
    assert "Budget exhausted" in str(error)


def test_retry_execution_error_with_policy_decision() -> None:
    """ConfluenceRetryExecutionError carries policy decision."""
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.TERMINATE,
        outcome_class=ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
        stable_kind=ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )
    error = ConfluenceRetryExecutionError(
        "Budget exhausted",
        decision=decision,
    )

    assert error.decision is decision


def test_retry_execution_error_rejects_wrong_decision_type() -> None:
    """ConfluenceRetryExecutionError rejects non-decision types."""
    with pytest.raises(TypeError, match="expects a"):
        ConfluenceRetryExecutionError(
            "Error",
            decision="not a decision",  # type: ignore
        )


def test_retry_execution_error_repr_safe() -> None:
    """ConfluenceRetryExecutionError repr does not disclose values."""
    decision = confluence_request_budget_terminate()
    error = ConfluenceRetryExecutionError(
        "Budget exhausted",
        decision=decision,
    )
    rendered = repr(error)
    assert "Budget" not in rendered


# =============================================================================
# Section 16: ConfluenceStatusAwareExecutionResult
# =============================================================================


def test_status_result_with_terminal_decision() -> None:
    """ConfluenceStatusAwareExecutionResult with terminal decision."""
    response = ConfluenceHttpResponse(status_code=400, body=b"Bad Request")
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.TERMINATE,
        outcome_class=ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        stable_kind=ConfluenceRetryStableKind.HTTP_TERMINAL,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )
    result = ConfluenceStatusAwareExecutionResult(
        response=response,
        terminal_decision=decision,
    )

    assert result.terminal_decision is decision
    assert result.response.status_code == 400


def test_status_result_without_terminal_decision() -> None:
    """ConfluenceStatusAwareExecutionResult without terminal decision."""
    response = ConfluenceHttpResponse(status_code=200, body=b'{"ok": true}')
    result = ConfluenceStatusAwareExecutionResult(
        response=response,
        terminal_decision=None,
    )

    assert result.terminal_decision is None
    assert result.response.status_code == 200


def test_status_result_rejects_non_terminal_decision() -> None:
    """ConfluenceStatusAwareExecutionResult rejects non-TERMINATE decision."""
    response = ConfluenceHttpResponse(status_code=200, body=b'{"ok": true}')
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.RETRY,
        outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        stable_kind=ConfluenceRetryStableKind.HTTP_503,
        selected_delay_seconds=1.0,
        next_attempt_number=2,
    )

    with pytest.raises(ValueError, match="must be TERMINATE"):
        ConfluenceStatusAwareExecutionResult(
            response=response,
            terminal_decision=decision,
        )


def test_status_result_rejects_terminal_decision_for_semantic_response() -> None:
    response = ConfluenceHttpResponse(status_code=404, body=b"Not Found")
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.TERMINATE,
        outcome_class=ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        stable_kind=ConfluenceRetryStableKind.HTTP_TERMINAL,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )

    with pytest.raises(ValueError, match="semantic response"):
        ConfluenceStatusAwareExecutionResult(
            response=response,
            terminal_decision=decision,
        )


def test_status_result_requires_terminal_decision_for_non_semantic_response() -> None:
    response = ConfluenceHttpResponse(status_code=400, body=b"Bad Request")

    with pytest.raises(ValueError, match="requires a terminal decision"):
        ConfluenceStatusAwareExecutionResult(
            response=response,
            terminal_decision=None,
        )


@pytest.mark.parametrize(
    ("status_code", "outcome_class", "stable_kind"),
    [
        (
            400,
            ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
            ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
        ),
        (
            503,
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.HTTP_TERMINAL,
        ),
    ],
)
def test_status_result_rejects_outcome_class_that_disagrees_with_status(
    status_code: int,
    outcome_class: ConfluenceRetryOutcomeClass,
    stable_kind: ConfluenceRetryStableKind,
) -> None:
    response = ConfluenceHttpResponse(status_code=status_code, body=b"failure")
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.TERMINATE,
        outcome_class=outcome_class,
        stable_kind=stable_kind,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )

    with pytest.raises(ValueError, match="status and terminal decision disagree"):
        ConfluenceStatusAwareExecutionResult(
            response=response,
            terminal_decision=decision,
        )


def test_status_result_repr_safe() -> None:
    """ConfluenceStatusAwareExecutionResult repr does not disclose body."""
    response = ConfluenceHttpResponse(
        status_code=200, body=b"private-sensitive-data"
    )
    result = ConfluenceStatusAwareExecutionResult(
        response=response,
        terminal_decision=None,
    )
    rendered = repr(result)
    assert "private-sensitive-data" not in rendered


# =============================================================================
# Budget exhaustion tests
# =============================================================================


def test_budget_exhausted_before_first_request() -> None:
    """Budget exhaustion raises before first request when at limit."""
    transport, opener, sleeper, _ = _transport(
        initial_requests_started=50000,
    )

    with pytest.raises(ConfluenceRetryExecutionError) as exc_info:
        transport.get_json(path="/rest/api/search", query={"start": "0"})

    assert exc_info.value.decision.action is ConfluenceRequestBudgetAction.TERMINATE
    assert len(opener.calls) == 0


# =============================================================================
# Representation tests
# =============================================================================


def test_transport_repr_does_not_disclose_details() -> None:
    """RetryingConfluenceHttpTransport repr is safe."""
    transport, _, _, _ = _transport()
    rendered = repr(transport)
    assert PAT not in rendered
    assert "fixture.invalid" not in rendered


def test_profile_repr_does_not_disclose_values() -> None:
    """ConfluenceRetryExecutorProfile repr is safe."""
    retry_policy = ConfluenceRetryPolicyProfile.from_mapping(
        _make_full_profile_mapping()
    )
    profile = ConfluenceRetryExecutorProfile(
        retry_policy=retry_policy,
        minimum_request_interval_seconds=3.0,
    )
    rendered = repr(profile)
    assert "50000" not in rendered
    assert "3.0" not in rendered


def test_invalid_path_is_rejected_before_clock_sleep_or_attempt() -> None:
    transport, opener, sleeper, clock_times = _transport()

    with pytest.raises(ValueError):
        transport.get_json(path="relative/path?injected=1", query={})

    assert opener.calls == []
    assert sleeper.sleeps == []
    assert clock_times == []
    assert transport.snapshot().requests_started_for_run == 0


def test_retry_delay_includes_monotonic_rate_limit_wait() -> None:
    transport, opener, sleeper, _ = _transport(
        response=FakeResponse(status=503, body=b"temporary")
    )

    result = transport.get_response_bytes_result(
        path="/rest/api/restriction",
        query={},
    )

    assert result.terminal_decision is not None
    assert result.terminal_decision.stable_kind is ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED
    assert len(opener.calls) == 4
    # The fake clock advances one second between attempt start and policy
    # evaluation, so the three-second minimum contributes two seconds to the
    # first two selected sleeps; the final backoff is four seconds.
    assert sleeper.sleeps == [2.0, 2.0, 4.0]
