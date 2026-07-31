from __future__ import annotations

import ast
import inspect
from enum import IntEnum
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceHttpFailureMetadata,
    ConfluenceRetryAfterMetadata,
    confluence_retry_after_absent,
    confluence_retry_after_ignored,
    confluence_retry_after_valid,
)
from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRequestBudgetAction,
    ConfluenceRetryEvaluationContext,
    ConfluenceRetryOutcomeClass,
    ConfluenceRetryPolicyAction,
    ConfluenceRetryPolicyProfile,
    ConfluenceRetryStableKind,
)
from knowledgenexus.foundation.domain.rules.confluence_retry_policy import (
    evaluate_confluence_http_failure,
    evaluate_confluence_request_budget,
    evaluate_confluence_restriction_response,
)


_FULL_PROFILE_MAPPING = {
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


def _profile() -> ConfluenceRetryPolicyProfile:
    return ConfluenceRetryPolicyProfile.from_mapping(_FULL_PROFILE_MAPPING)


def _context(
    *,
    current_attempt_number: int = 1,
    requests_started_for_run: int | None = None,
    accumulated_retry_sleep_seconds: float = 0.0,
    rate_limit_wait_seconds: float = 0.0,
) -> ConfluenceRetryEvaluationContext:
    if requests_started_for_run is None:
        requests_started_for_run = current_attempt_number
    return ConfluenceRetryEvaluationContext(
        current_attempt_number=current_attempt_number,
        requests_started_for_run=requests_started_for_run,
        accumulated_retry_sleep_seconds=accumulated_retry_sleep_seconds,
        rate_limit_wait_seconds=rate_limit_wait_seconds,
    )


def _http_status_metadata(
    status: int,
    retry_after: ConfluenceRetryAfterMetadata | None = None,
) -> ConfluenceHttpFailureMetadata:
    return ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.HTTP_STATUS,
        http_status=status,
        retry_after=retry_after or confluence_retry_after_absent(),
    )


# ---------------------------------------------------------------------------
# A. Request-budget preflight
# ---------------------------------------------------------------------------


def test_request_budget_allow_at_zero() -> None:
    decision = evaluate_confluence_request_budget(
        requests_started_for_run=0, profile=_profile()
    )
    assert decision.action is ConfluenceRequestBudgetAction.ALLOW_ATTEMPT


def test_request_budget_allow_at_49999_of_50000() -> None:
    decision = evaluate_confluence_request_budget(
        requests_started_for_run=49999, profile=_profile()
    )
    assert decision.action is ConfluenceRequestBudgetAction.ALLOW_ATTEMPT


def test_request_budget_terminate_at_50000_of_50000() -> None:
    decision = evaluate_confluence_request_budget(
        requests_started_for_run=50000, profile=_profile()
    )
    assert decision.action is ConfluenceRequestBudgetAction.TERMINATE
    assert decision.stable_kind is ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED


def test_request_budget_rejects_over_limit() -> None:
    with pytest.raises(ValueError):
        evaluate_confluence_request_budget(
            requests_started_for_run=50001, profile=_profile()
        )


def test_request_budget_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        evaluate_confluence_request_budget(
            requests_started_for_run=-1, profile=_profile()
        )


def test_request_budget_rejects_bool_count() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_request_budget(
            requests_started_for_run=True, profile=_profile()  # type: ignore[arg-type]
        )


def test_request_budget_rejects_int_enum_count() -> None:
    class Count(IntEnum):
        ZERO = 0

    with pytest.raises(TypeError):
        evaluate_confluence_request_budget(
            requests_started_for_run=Count.ZERO,
            profile=_profile(),
        )


def test_request_budget_rejects_wrong_profile_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_request_budget(
            requests_started_for_run=0, profile=object()  # type: ignore[arg-type]
        )


def test_request_budget_does_not_mutate_profile() -> None:
    profile = _profile()
    evaluate_confluence_request_budget(requests_started_for_run=10, profile=profile)
    assert profile.max_total_requests_per_run == 50000


# ---------------------------------------------------------------------------
# B. Profile-relative validation before classification
# ---------------------------------------------------------------------------


_FACT_EVALUATORS = {
    "semantic": lambda ctx, profile: evaluate_confluence_restriction_response(
        status_code=200,
        retry_after=confluence_retry_after_absent(),
        context=ctx,
        profile=profile,
    ),
    "terminal_http": lambda ctx, profile: evaluate_confluence_http_failure(
        metadata=_http_status_metadata(400), context=ctx, profile=profile
    ),
    "retryable_http": lambda ctx, profile: evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500), context=ctx, profile=profile
    ),
    "missing_metadata": lambda ctx, profile: evaluate_confluence_http_failure(
        metadata=None, context=ctx, profile=profile
    ),
}


@pytest.mark.parametrize("fact_key", list(_FACT_EVALUATORS.keys()))
def test_attempt_over_limit_rejected_before_classification(fact_key: str) -> None:
    profile = _profile()
    ctx = _context(current_attempt_number=5, requests_started_for_run=5)
    with pytest.raises(ValueError):
        _FACT_EVALUATORS[fact_key](ctx, profile)


@pytest.mark.parametrize("fact_key", list(_FACT_EVALUATORS.keys()))
def test_requests_over_limit_rejected_before_classification(fact_key: str) -> None:
    profile = _profile()
    ctx = _context(current_attempt_number=1, requests_started_for_run=50001)
    with pytest.raises(ValueError):
        _FACT_EVALUATORS[fact_key](ctx, profile)


@pytest.mark.parametrize("fact_key", list(_FACT_EVALUATORS.keys()))
def test_accumulated_delay_over_limit_rejected_before_classification(
    fact_key: str,
) -> None:
    profile = _profile()
    ctx = _context(
        current_attempt_number=1,
        requests_started_for_run=1,
        accumulated_retry_sleep_seconds=301.0,
    )
    with pytest.raises(ValueError):
        _FACT_EVALUATORS[fact_key](ctx, profile)


def test_http_failure_evaluator_rejects_wrong_profile_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_http_failure(
            metadata=_http_status_metadata(500),
            context=_context(),
            profile=object(),  # type: ignore[arg-type]
        )


def test_http_failure_evaluator_rejects_wrong_context_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_http_failure(
            metadata=_http_status_metadata(500),
            context=object(),  # type: ignore[arg-type]
            profile=_profile(),
        )


def test_restriction_evaluator_rejects_wrong_profile_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_restriction_response(
            status_code=200,
            retry_after=confluence_retry_after_absent(),
            context=_context(),
            profile=object(),  # type: ignore[arg-type]
        )


def test_restriction_evaluator_rejects_wrong_context_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_restriction_response(
            status_code=200,
            retry_after=confluence_retry_after_absent(),
            context=object(),  # type: ignore[arg-type]
            profile=_profile(),
        )


def test_http_failure_evaluator_rejects_wrong_metadata_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_http_failure(
            metadata=object(),  # type: ignore[arg-type]
            context=_context(),
            profile=_profile(),
        )


def test_restriction_evaluator_rejects_wrong_retry_after_type() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_restriction_response(
            status_code=500,
            retry_after=object(),  # type: ignore[arg-type]
            context=_context(),
            profile=_profile(),
        )


# ---------------------------------------------------------------------------
# C. HTTP classifications
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected_kind",
    [
        (408, ConfluenceRetryStableKind.HTTP_408),
        (429, ConfluenceRetryStableKind.HTTP_429),
        (500, ConfluenceRetryStableKind.HTTP_500),
        (502, ConfluenceRetryStableKind.HTTP_502),
        (503, ConfluenceRetryStableKind.HTTP_503),
        (504, ConfluenceRetryStableKind.HTTP_504),
    ],
)
def test_exact_retryable_statuses(
    status: int, expected_kind: ConfluenceRetryStableKind
) -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(status),
        context=_context(),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.RETRY
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE
    assert decision.stable_kind is expected_kind


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 409, 422, 501, 505])
def test_representative_terminal_statuses(status: int) -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(status),
        context=_context(),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.HTTP_TERMINAL


def test_unexpected_200_inside_http_status_metadata_is_terminal() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(200),
        context=_context(),
        profile=_profile(),
    )
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.HTTP_TERMINAL


def test_redirect_is_terminal() -> None:
    metadata = ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE,
        http_status=302,
        retry_after=confluence_retry_after_absent(),
    )
    decision = evaluate_confluence_http_failure(
        metadata=metadata, context=_context(), profile=_profile()
    )
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE


def test_invalid_http_status_is_terminal() -> None:
    metadata = ConfluenceHttpFailureMetadata(
        kind=ConfluenceHttpFailureKind.INVALID_HTTP_STATUS,
        http_status=None,
        retry_after=confluence_retry_after_absent(),
    )
    decision = evaluate_confluence_http_failure(
        metadata=metadata, context=_context(), profile=_profile()
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.INVALID_HTTP_STATUS


def test_no_range_based_retry_for_other_5xx() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(507),
        context=_context(),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.stable_kind is ConfluenceRetryStableKind.HTTP_TERMINAL


# ---------------------------------------------------------------------------
# D. Transport and payload classifications
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected_outcome,expected_stable",
    [
        (
            ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT,
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.TRANSPORT_TIMEOUT,
        ),
        (
            ConfluenceHttpFailureKind.CONNECTION_RESET,
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.CONNECTION_RESET,
        ),
        (
            ConfluenceHttpFailureKind.CONNECTION_ABORTED,
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.CONNECTION_ABORTED,
        ),
        (
            ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE,
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.TEMPORARY_CONNECTION_FAILURE,
        ),
        (
            ConfluenceHttpFailureKind.TEMPORARY_DNS_FAILURE,
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.TEMPORARY_DNS_FAILURE,
        ),
        (
            ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR,
            ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
        ),
        (
            ConfluenceHttpFailureKind.PERMANENT_DNS_FAILURE,
            ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.PERMANENT_DNS_FAILURE,
        ),
        (
            ConfluenceHttpFailureKind.TLS_CERTIFICATE_FAILURE,
            ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.TLS_CERTIFICATE_FAILURE,
        ),
        (
            ConfluenceHttpFailureKind.INVALID_URL,
            ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.INVALID_URL,
        ),
        (
            ConfluenceHttpFailureKind.RESPONSE_TOO_LARGE,
            ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
            ConfluenceRetryStableKind.RESPONSE_TOO_LARGE,
        ),
        (
            ConfluenceHttpFailureKind.MALFORMED_JSON,
            ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
            ConfluenceRetryStableKind.MALFORMED_JSON,
        ),
        (
            ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE,
            ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
            ConfluenceRetryStableKind.PAYLOAD_VALIDATION_FAILURE,
        ),
    ],
)
def test_transport_and_payload_classifications(
    kind: ConfluenceHttpFailureKind,
    expected_outcome: ConfluenceRetryOutcomeClass,
    expected_stable: ConfluenceRetryStableKind,
) -> None:
    metadata = ConfluenceHttpFailureMetadata(
        kind=kind, http_status=None, retry_after=confluence_retry_after_absent()
    )
    decision = evaluate_confluence_http_failure(
        metadata=metadata, context=_context(), profile=_profile()
    )
    assert decision.outcome_class is expected_outcome
    assert decision.stable_kind is expected_stable


def test_missing_metadata_is_terminal_unclassified() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=None, context=_context(), profile=_profile()
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR


# ---------------------------------------------------------------------------
# E. Restriction responses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 401, 403, 404])
def test_restriction_semantic_statuses(status: int) -> None:
    decision = evaluate_confluence_restriction_response(
        status_code=status,
        retry_after=confluence_retry_after_absent(),
        context=_context(),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION
    assert decision.stable_kind is None


@pytest.mark.parametrize(
    "status,expected_kind",
    [
        (408, ConfluenceRetryStableKind.HTTP_408),
        (429, ConfluenceRetryStableKind.HTTP_429),
        (500, ConfluenceRetryStableKind.HTTP_500),
        (502, ConfluenceRetryStableKind.HTTP_502),
        (503, ConfluenceRetryStableKind.HTTP_503),
        (504, ConfluenceRetryStableKind.HTTP_504),
    ],
)
def test_restriction_retryable_statuses(
    status: int, expected_kind: ConfluenceRetryStableKind
) -> None:
    decision = evaluate_confluence_restriction_response(
        status_code=status,
        retry_after=confluence_retry_after_absent(),
        context=_context(),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.RETRY
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE
    assert decision.stable_kind is expected_kind


@pytest.mark.parametrize("status", [300, 301, 399])
def test_restriction_3xx_is_terminal_redirect(status: int) -> None:
    decision = evaluate_confluence_restriction_response(
        status_code=status,
        retry_after=confluence_retry_after_absent(),
        context=_context(),
        profile=_profile(),
    )
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE


@pytest.mark.parametrize("status", [400, 405, 409, 410, 422, 501, 505])
def test_restriction_other_statuses_are_terminal_http(status: int) -> None:
    decision = evaluate_confluence_restriction_response(
        status_code=status,
        retry_after=confluence_retry_after_absent(),
        context=_context(),
        profile=_profile(),
    )
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.HTTP_TERMINAL


def test_restriction_evaluator_has_no_body_parameter() -> None:
    signature = inspect.signature(evaluate_confluence_restriction_response)
    assert "body" not in signature.parameters


def test_restriction_evaluator_rejects_bool_status_code() -> None:
    with pytest.raises(TypeError):
        evaluate_confluence_restriction_response(
            status_code=True,  # type: ignore[arg-type]
            retry_after=confluence_retry_after_absent(),
            context=_context(),
            profile=_profile(),
        )


def test_restriction_evaluator_rejects_out_of_range_status_code() -> None:
    with pytest.raises(ValueError):
        evaluate_confluence_restriction_response(
            status_code=999,
            retry_after=confluence_retry_after_absent(),
            context=_context(),
            profile=_profile(),
        )


# ---------------------------------------------------------------------------
# F. Attempts and backoff
# ---------------------------------------------------------------------------


def test_backoff_after_attempt_1_is_1_0() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 1.0
    assert decision.next_attempt_number == 2


def test_backoff_after_attempt_2_is_2_0() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=2, requests_started_for_run=2),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 2.0
    assert decision.next_attempt_number == 3


def test_backoff_after_attempt_3_is_4_0() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=3, requests_started_for_run=3),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 4.0
    assert decision.next_attempt_number == 4


def test_failure_after_attempt_4_is_attempts_exhausted() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=4, requests_started_for_run=4),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED
    assert decision.stable_kind is ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED
    assert decision.selected_delay_seconds is None


# ---------------------------------------------------------------------------
# G. Retry-After and rate-limit interaction
# ---------------------------------------------------------------------------


def test_absent_retry_after_uses_backoff() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_absent()),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 1.0


def test_ignored_retry_after_uses_backoff() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_ignored()),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 1.0


def test_valid_zero_retry_after_uses_backoff() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(0)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 1.0


def test_valid_30_retry_after_selects_30() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(30)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 30.0


def test_valid_120_retry_after_is_allowed() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(120)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.RETRY
    assert decision.selected_delay_seconds == 120.0


def test_valid_above_120_retry_after_terminates_without_delay() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(121)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.stable_kind is ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY
    assert decision.selected_delay_seconds is None


def test_extremely_large_retry_after_terminates_without_overflow() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(
            500,
            confluence_retry_after_valid(10**4000),
        ),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert (
        decision.stable_kind
        is ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY
    )
    assert decision.selected_delay_seconds is None


def test_rate_limit_wait_greater_than_retry_component_wins() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_absent()),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            rate_limit_wait_seconds=50.0,
        ),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 50.0


def test_components_are_never_added() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(30)),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            rate_limit_wait_seconds=20.0,
        ),
        profile=_profile(),
    )
    # max(backoff=1.0, retry_after=30.0)=30.0; max(rate_wait=20.0, 30.0)=30.0.
    # A summing implementation would incorrectly produce 1.0 + 30.0 + 20.0.
    assert decision.selected_delay_seconds == 30.0


# ---------------------------------------------------------------------------
# H. Delay budgets
# ---------------------------------------------------------------------------


def test_selected_delay_equal_to_120_allowed() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(120)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.RETRY


def test_selected_delay_above_120_denied() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_absent()),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            rate_limit_wait_seconds=130.0,
        ),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.stable_kind is ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED


def test_extremely_large_rate_limit_wait_terminates_without_overflow() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_absent()),
        context=ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=10**4000,
        ),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert (
        decision.stable_kind
        is ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED
    )
    assert decision.selected_delay_seconds is None


def test_projected_total_equal_to_300_allowed() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(100)),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=200.0,
        ),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.RETRY
    assert decision.selected_delay_seconds == 100.0


def test_projected_total_above_300_denied() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(100)),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=200.5,
        ),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.TERMINATE
    assert decision.stable_kind is ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED


def test_fractional_boundary_not_rounded() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(100.001)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.selected_delay_seconds == 100.001


# ---------------------------------------------------------------------------
# I. Decision precedence
# ---------------------------------------------------------------------------


def test_final_attempt_plus_oversized_retry_after_is_attempts_exhausted() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(600)),
        context=_context(current_attempt_number=4, requests_started_for_run=4),
        profile=_profile(),
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED


def test_request_budget_exhausted_plus_oversized_retry_after() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(600)),
        context=_context(current_attempt_number=1, requests_started_for_run=50000),
        profile=_profile(),
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED


def test_attempts_and_budget_available_plus_oversized_retry_after() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(600)),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=_profile(),
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY


def test_attempt_exhausted_precedes_request_budget_exhausted() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=4, requests_started_for_run=50000),
        profile=_profile(),
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED


def test_retry_after_over_cap_precedes_rate_limit_check() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500, confluence_retry_after_valid(600)),
        context=_context(
            current_attempt_number=1,
            requests_started_for_run=1,
            rate_limit_wait_seconds=600.0,
        ),
        profile=_profile(),
    )
    assert decision.stable_kind is ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY


def test_terminal_http_with_valid_boundary_budgets_still_terminal() -> None:
    decision = evaluate_confluence_http_failure(
        metadata=_http_status_metadata(400),
        context=_context(current_attempt_number=4, requests_started_for_run=50000),
        profile=_profile(),
    )
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
    assert decision.stable_kind is ConfluenceRetryStableKind.HTTP_TERMINAL


def test_semantic_observation_with_valid_boundary_budgets_still_semantic() -> None:
    decision = evaluate_confluence_restriction_response(
        status_code=200,
        retry_after=confluence_retry_after_absent(),
        context=_context(current_attempt_number=4, requests_started_for_run=50000),
        profile=_profile(),
    )
    assert decision.action is ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION


# ---------------------------------------------------------------------------
# J. Purity
# ---------------------------------------------------------------------------


def test_purity_same_inputs_produce_value_equal_decisions() -> None:
    profile = _profile()
    context = _context(current_attempt_number=1, requests_started_for_run=1)
    metadata = _http_status_metadata(500)

    first = evaluate_confluence_http_failure(
        metadata=metadata, context=context, profile=profile
    )
    second = evaluate_confluence_http_failure(
        metadata=metadata, context=context, profile=profile
    )
    assert first == second


def test_purity_profile_mapping_not_mutated() -> None:
    mapping = dict(_FULL_PROFILE_MAPPING)
    snapshot = dict(mapping)
    profile = ConfluenceRetryPolicyProfile.from_mapping(mapping)

    evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500),
        context=_context(current_attempt_number=1, requests_started_for_run=1),
        profile=profile,
    )

    assert mapping == snapshot


def test_purity_models_not_mutated_across_calls() -> None:
    profile = _profile()
    context = _context(current_attempt_number=1, requests_started_for_run=1)

    evaluate_confluence_http_failure(
        metadata=_http_status_metadata(500), context=context, profile=profile
    )

    assert profile.max_attempts == 4
    assert context.current_attempt_number == 1


_FORBIDDEN_MODULE_ROOTS = frozenset(
    {
        "urllib",
        "socket",
        "ssl",
        "http",
        "yaml",
        "pathlib",
        "os",
        "time",
        "datetime",
        "logging",
    }
)

_B2_PRODUCTION_MODULE_PATHS = (
    ("foundation", "domain", "models", "confluence_retry_policy.py"),
    ("foundation", "domain", "rules", "confluence_retry_policy.py"),
)


def test_production_modules_have_no_forbidden_imports() -> None:
    repo_root = Path(__file__).resolve().parents[4]

    for relative_parts in _B2_PRODUCTION_MODULE_PATHS:
        module_path = repo_root.joinpath("src", "knowledgenexus", *relative_parts)
        tree = ast.parse(module_path.read_text(encoding="utf-8"))

        imported_roots: set[str] = set()
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
                imported_modules.add(node.module)

        assert imported_roots.isdisjoint(_FORBIDDEN_MODULE_ROOTS), module_path
        assert not any(
            "infrastructure" in module_name for module_name in imported_modules
        ), module_path
