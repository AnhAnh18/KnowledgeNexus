from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceHttpFailureMetadata,
    ConfluenceRetryAfterMetadata,
    ConfluenceRetryAfterState,
    confluence_retry_after_absent,
)
from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRequestBudgetDecision,
    ConfluenceRetryEvaluationContext,
    ConfluenceRetryOutcomeClass,
    ConfluenceRetryPolicyAction,
    ConfluenceRetryPolicyDecision,
    ConfluenceRetryPolicyProfile,
    ConfluenceRetryStableKind,
    confluence_request_budget_allow,
    confluence_request_budget_terminate,
)

# Section 6: exactly these HTTP statuses are retryable, mapped to their exact
# stable kind. No generic 4xx/5xx range retry exists anywhere in this module.
_RETRYABLE_HTTP_STATUS_KIND: Mapping[int, ConfluenceRetryStableKind] = MappingProxyType({
    408: ConfluenceRetryStableKind.HTTP_408,
    429: ConfluenceRetryStableKind.HTTP_429,
    500: ConfluenceRetryStableKind.HTTP_500,
    502: ConfluenceRetryStableKind.HTTP_502,
    503: ConfluenceRetryStableKind.HTTP_503,
    504: ConfluenceRetryStableKind.HTTP_504,
})

# Section 13.3: exact typed transport failure-kind bindings (retryable and
# terminal). Section 13.4: exact typed payload failure-kind bindings
# (always terminal).
_TRANSPORT_AND_PAYLOAD_KIND_MAP: Mapping[
    ConfluenceHttpFailureKind,
    tuple[ConfluenceRetryOutcomeClass, ConfluenceRetryStableKind],
] = MappingProxyType({
    ConfluenceHttpFailureKind.TRANSPORT_TIMEOUT: (
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.TRANSPORT_TIMEOUT,
    ),
    ConfluenceHttpFailureKind.CONNECTION_RESET: (
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.CONNECTION_RESET,
    ),
    ConfluenceHttpFailureKind.CONNECTION_ABORTED: (
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.CONNECTION_ABORTED,
    ),
    ConfluenceHttpFailureKind.TEMPORARY_CONNECTION_FAILURE: (
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.TEMPORARY_CONNECTION_FAILURE,
    ),
    ConfluenceHttpFailureKind.TEMPORARY_DNS_FAILURE: (
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.TEMPORARY_DNS_FAILURE,
    ),
    ConfluenceHttpFailureKind.UNCLASSIFIED_OS_ERROR: (
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
    ),
    ConfluenceHttpFailureKind.PERMANENT_DNS_FAILURE: (
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.PERMANENT_DNS_FAILURE,
    ),
    ConfluenceHttpFailureKind.TLS_CERTIFICATE_FAILURE: (
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.TLS_CERTIFICATE_FAILURE,
    ),
    ConfluenceHttpFailureKind.INVALID_URL: (
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.INVALID_URL,
    ),
    ConfluenceHttpFailureKind.RESPONSE_TOO_LARGE: (
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
        ConfluenceRetryStableKind.RESPONSE_TOO_LARGE,
    ),
    ConfluenceHttpFailureKind.MALFORMED_JSON: (
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
        ConfluenceRetryStableKind.MALFORMED_JSON,
    ),
    ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE: (
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
        ConfluenceRetryStableKind.PAYLOAD_VALIDATION_FAILURE,
    ),
})

_SEMANTIC_RESTRICTION_STATUSES = frozenset({200, 401, 403, 404})

_TERMINATE_TERMINAL_CLASSES = frozenset(
    {
        ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
    }
)


def evaluate_confluence_request_budget(
    *,
    requests_started_for_run: int,
    profile: ConfluenceRetryPolicyProfile,
) -> ConfluenceRequestBudgetDecision:
    """Section 12: pure request-budget preflight. Reserves nothing."""

    if not isinstance(profile, ConfluenceRetryPolicyProfile):
        raise TypeError("profile expects a ConfluenceRetryPolicyProfile")
    if type(requests_started_for_run) is not int:
        raise TypeError("requests_started_for_run expects an exact int")
    if requests_started_for_run < 0:
        raise ValueError("requests_started_for_run must be non-negative")
    if requests_started_for_run > profile.max_total_requests_per_run:
        raise ValueError(
            "requests_started_for_run must not exceed the profile request limit"
        )

    if requests_started_for_run < profile.max_total_requests_per_run:
        return confluence_request_budget_allow()
    return confluence_request_budget_terminate()


def _validate_profile_relative_context(
    *,
    context: ConfluenceRetryEvaluationContext,
    profile: ConfluenceRetryPolicyProfile,
) -> None:
    """Section 7: mandatory profile-relative validation before classification."""

    if not isinstance(profile, ConfluenceRetryPolicyProfile):
        raise TypeError("profile expects a ConfluenceRetryPolicyProfile")
    if not isinstance(context, ConfluenceRetryEvaluationContext):
        raise TypeError("context expects a ConfluenceRetryEvaluationContext")

    if context.current_attempt_number > profile.max_attempts:
        raise ValueError("current_attempt_number exceeds the profile attempt limit")
    if context.requests_started_for_run > profile.max_total_requests_per_run:
        raise ValueError(
            "requests_started_for_run exceeds the profile request limit"
        )
    if context.accumulated_retry_sleep_seconds > profile.max_total_retry_delay_seconds:
        raise ValueError(
            "accumulated_retry_sleep_seconds exceeds the profile total delay limit"
        )


def _classify_http_failure(
    metadata: ConfluenceHttpFailureMetadata | None,
) -> tuple[ConfluenceRetryOutcomeClass, ConfluenceRetryStableKind]:
    """Section 13.1-13.4: classify one observed HTTP transport fact."""

    if metadata is None:
        # Section 13.1: legacy missing metadata is never retried.
        return (
            ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
        )
    if not isinstance(metadata, ConfluenceHttpFailureMetadata):
        raise TypeError("metadata expects a ConfluenceHttpFailureMetadata or None")

    if metadata.kind is ConfluenceHttpFailureKind.HTTP_STATUS:
        stable_kind = _RETRYABLE_HTTP_STATUS_KIND.get(metadata.http_status)
        if stable_kind is not None:
            return ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE, stable_kind
        return (
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.HTTP_TERMINAL,
        )

    if metadata.kind is ConfluenceHttpFailureKind.REDIRECT_POLICY_FAILURE:
        return (
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE,
        )

    if metadata.kind is ConfluenceHttpFailureKind.INVALID_HTTP_STATUS:
        return (
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.INVALID_HTTP_STATUS,
        )

    mapped = _TRANSPORT_AND_PAYLOAD_KIND_MAP.get(metadata.kind)
    if mapped is None:
        raise ValueError("unrecognized ConfluenceHttpFailureKind")
    return mapped


def _terminate_decision(
    outcome_class: ConfluenceRetryOutcomeClass,
    stable_kind: ConfluenceRetryStableKind,
) -> ConfluenceRetryPolicyDecision:
    return ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.TERMINATE,
        outcome_class=outcome_class,
        stable_kind=stable_kind,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )


def _budget_exhausted_decision(
    stable_kind: ConfluenceRetryStableKind,
) -> ConfluenceRetryPolicyDecision:
    return _terminate_decision(ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED, stable_kind)


def _apply_bounded_retry(
    *,
    outcome_class: ConfluenceRetryOutcomeClass,
    stable_kind: ConfluenceRetryStableKind,
    retry_after: ConfluenceRetryAfterMetadata,
    context: ConfluenceRetryEvaluationContext,
    profile: ConfluenceRetryPolicyProfile,
) -> ConfluenceRetryPolicyDecision:
    """Section 14: the normative bounded-retry precedence for one retryable fact."""

    # Step 1 — attempt limit.
    if context.current_attempt_number >= profile.max_attempts:
        return _budget_exhausted_decision(ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED)

    # Step 2 — request budget for the next attempt.
    if context.requests_started_for_run >= profile.max_total_requests_per_run:
        return _budget_exhausted_decision(
            ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED
        )

    # Step 3 — oversized valid Retry-After; never clamped.
    if (
        retry_after.state is ConfluenceRetryAfterState.VALID
        and retry_after.delay_seconds > profile.max_retry_delay_seconds
    ):
        return _budget_exhausted_decision(
            ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY
        )

    # Step 4 — deterministic client backoff.
    retry_ordinal = context.current_attempt_number
    client_backoff = min(
        profile.max_retry_delay_seconds,
        profile.base_backoff_seconds * (2 ** (retry_ordinal - 1)),
    )

    # Step 5 — select exactly one delay; components are never summed.
    retry_after_seconds = (
        float(retry_after.delay_seconds)
        if retry_after.state is ConfluenceRetryAfterState.VALID
        else 0.0
    )
    retry_component = max(client_backoff, retry_after_seconds)
    if context.rate_limit_wait_seconds > profile.max_retry_delay_seconds:
        return _budget_exhausted_decision(
            ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED
        )
    selected_delay = max(float(context.rate_limit_wait_seconds), retry_component)

    # Step 6 — single-delay bound; equality allowed.
    if selected_delay > profile.max_retry_delay_seconds:
        return _budget_exhausted_decision(
            ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED
        )

    # Step 7 — accumulated-delay bound; equality allowed.
    projected_total = float(context.accumulated_retry_sleep_seconds) + selected_delay
    if projected_total > profile.max_total_retry_delay_seconds:
        return _budget_exhausted_decision(
            ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED
        )

    # Step 8 — retry.
    return ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.RETRY,
        outcome_class=outcome_class,
        stable_kind=stable_kind,
        selected_delay_seconds=float(selected_delay),
        next_attempt_number=context.current_attempt_number + 1,
    )


def evaluate_confluence_http_failure(
    *,
    metadata: ConfluenceHttpFailureMetadata | None,
    context: ConfluenceRetryEvaluationContext,
    profile: ConfluenceRetryPolicyProfile,
) -> ConfluenceRetryPolicyDecision:
    """Classify one observed HTTP/transport/payload fact and apply bounded retry."""

    _validate_profile_relative_context(context=context, profile=profile)

    outcome_class, stable_kind = _classify_http_failure(metadata)

    if outcome_class in _TERMINATE_TERMINAL_CLASSES:
        return _terminate_decision(outcome_class, stable_kind)

    retry_after = (
        metadata.retry_after if metadata is not None else confluence_retry_after_absent()
    )
    return _apply_bounded_retry(
        outcome_class=outcome_class,
        stable_kind=stable_kind,
        retry_after=retry_after,
        context=context,
        profile=profile,
    )


def evaluate_confluence_restriction_response(
    *,
    status_code: int,
    retry_after: ConfluenceRetryAfterMetadata,
    context: ConfluenceRetryEvaluationContext,
    profile: ConfluenceRetryPolicyProfile,
) -> ConfluenceRetryPolicyDecision:
    """Section 13.5: classify one Confluence view-restriction HTTP status.

    The response body is never an input to this evaluator.
    """

    _validate_profile_relative_context(context=context, profile=profile)

    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise TypeError("status_code expects an exact int")
    if status_code < 100 or status_code > 599:
        raise ValueError("status_code must be between 100 and 599")
    if not isinstance(retry_after, ConfluenceRetryAfterMetadata):
        raise TypeError("retry_after expects a ConfluenceRetryAfterMetadata")

    if status_code in _SEMANTIC_RESTRICTION_STATUSES:
        return ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION,
            outcome_class=ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION,
            stable_kind=None,
            selected_delay_seconds=None,
            next_attempt_number=None,
        )

    retryable_stable_kind = _RETRYABLE_HTTP_STATUS_KIND.get(status_code)
    if retryable_stable_kind is not None:
        return _apply_bounded_retry(
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=retryable_stable_kind,
            retry_after=retry_after,
            context=context,
            profile=profile,
        )

    if 300 <= status_code < 400:
        return _terminate_decision(
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE,
        )

    return _terminate_decision(
        ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_TERMINAL,
    )
