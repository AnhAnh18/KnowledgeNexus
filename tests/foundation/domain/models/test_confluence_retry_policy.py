from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRequestBudgetAction,
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
from knowledgenexus.shared.config.settings import get_settings


# Get paths from Settings (single source of truth)
_settings = get_settings()
REPOSITORY_ROOT = _settings.project_root
PROFILE_PATH = _settings.confluence_reliability_profile_path


def _load_raw_profile_mapping() -> dict:
    with PROFILE_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _valid_profile_mapping() -> dict:
    return dict(_load_raw_profile_mapping())


# ---------------------------------------------------------------------------
# A. Exact profile binding
# ---------------------------------------------------------------------------


def test_actual_approved_yaml_mapping_is_accepted() -> None:
    raw_mapping = _load_raw_profile_mapping()

    profile = ConfluenceRetryPolicyProfile.from_mapping(raw_mapping)

    assert profile.profile_id == "m7-crawl-reliability-v1"
    assert profile.profile_version == "1"
    assert profile.max_total_requests_per_run == 50000
    assert profile.max_attempts == 4
    assert profile.base_backoff_seconds == 1.0
    assert profile.max_retry_delay_seconds == 120.0
    assert profile.max_total_retry_delay_seconds == 300.0
    assert profile.jitter is False


def test_yaml_mapping_is_not_mutated_by_from_mapping() -> None:
    raw_mapping = _load_raw_profile_mapping()
    snapshot = dict(raw_mapping)

    ConfluenceRetryPolicyProfile.from_mapping(raw_mapping)

    assert raw_mapping == snapshot


def test_wrong_profile_id_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["profile_id"] = "m7-crawl-reliability-v2"
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_wrong_profile_version_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["profile_version"] = "2"
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


@pytest.mark.parametrize("missing_key", list(_valid_profile_mapping().keys()))
def test_each_missing_key_rejected(missing_key: str) -> None:
    mapping = _valid_profile_mapping()
    del mapping[missing_key]
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_additional_key_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["unexpected_extra_field"] = 1
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


@pytest.mark.parametrize(
    "key,replacement",
    [
        ("profile_id", "other-profile"),
        ("profile_version", "1.0"),
        ("inventory_page_size", 51),
        ("attachment_page_size", 51),
        ("minimum_request_interval_seconds", 4.0),
        ("max_response_bytes_per_request", 1),
        ("max_total_requests_per_run", 1),
        ("max_attempts", 5),
        ("base_backoff_seconds", 2.0),
        ("max_retry_delay_seconds", 121.0),
        ("max_total_retry_delay_seconds", 301.0),
        ("jitter", True),
        ("max_include_roots", 17),
        ("max_pages_per_run", 1),
        ("max_inventory_windows_per_root", 1),
        ("max_inventory_windows_per_run", 1),
        ("max_restriction_targets_per_page", 1),
        ("max_restriction_observations_per_run", 1),
        ("max_attachment_windows_per_page", 1),
        ("max_attachment_windows_per_run", 1),
        ("max_raw_bytes_per_run", 1),
        ("max_raw_artifacts_per_run", 1),
        ("minimum_free_disk_reserve_bytes", 1),
    ],
)
def test_mutation_of_every_approved_key_rejected(key: str, replacement: object) -> None:
    mapping = _valid_profile_mapping()
    mapping[key] = replacement
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_int_substituted_for_approved_float_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["base_backoff_seconds"] = 1
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_bool_substituted_for_approved_integer_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["max_attempts"] = True
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_string_number_rejected() -> None:
    mapping = _valid_profile_mapping()
    mapping["max_attempts"] = "4"
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(mapping)


def test_non_mapping_input_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile.from_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_unapproved_key_name_is_not_echoed_in_the_error() -> None:
    """An unapproved key is arbitrary caller data and must not reach the message."""
    mapping = _valid_profile_mapping()
    mapping["Bearer_ABC123_token"] = "https://wiki.internal.example/x"
    with pytest.raises(ValueError) as excinfo:
        ConfluenceRetryPolicyProfile.from_mapping(mapping)
    rendered = str(excinfo.value)
    assert "Bearer_ABC123_token" not in rendered
    assert "wiki.internal.example" not in rendered


def test_wrong_value_error_does_not_echo_supplied_value() -> None:
    mapping = _valid_profile_mapping()
    mapping["max_attempts"] = 987654321
    with pytest.raises(ValueError) as excinfo:
        ConfluenceRetryPolicyProfile.from_mapping(mapping)
    assert "987654321" not in str(excinfo.value)


def test_approved_profile_binding_is_immutable() -> None:
    """Rebinding the approved mapping would silently redefine 'approved'."""
    from knowledgenexus.foundation.domain.models import confluence_retry_policy as module

    with pytest.raises(TypeError):
        module._EXPECTED_PROFILE_V1["max_attempts"] = 999  # type: ignore[index]


def test_outcome_class_stable_kind_table_is_immutable() -> None:
    from knowledgenexus.foundation.domain.models import confluence_retry_policy as module

    with pytest.raises(TypeError):
        module._OUTCOME_CLASS_STABLE_KINDS[  # type: ignore[index]
            ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION
        ] = frozenset()


def test_profile_repr_hides_values() -> None:
    profile = ConfluenceRetryPolicyProfile.from_mapping(_valid_profile_mapping())
    rendered = repr(profile)
    assert rendered == "ConfluenceRetryPolicyProfile()"
    assert "50000" not in rendered
    assert "m7-crawl-reliability-v1" not in rendered


def test_direct_constructor_rejects_arbitrary_values() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyProfile(
            profile_id="m7-crawl-reliability-v1",
            profile_version="1",
            max_total_requests_per_run=1,
            max_attempts=4,
            base_backoff_seconds=1.0,
            max_retry_delay_seconds=120.0,
            max_total_retry_delay_seconds=300.0,
            jitter=False,
        )


def _approved_profile() -> ConfluenceRetryPolicyProfile:
    return ConfluenceRetryPolicyProfile.from_mapping(_valid_profile_mapping())


# ---------------------------------------------------------------------------
# B. Evaluation context
# ---------------------------------------------------------------------------


def test_context_accepts_valid_minimum_values() -> None:
    context = ConfluenceRetryEvaluationContext(
        current_attempt_number=1,
        requests_started_for_run=1,
        accumulated_retry_sleep_seconds=0,
        rate_limit_wait_seconds=0,
    )
    assert context.current_attempt_number == 1


def test_context_rejects_bool_current_attempt_number() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=True,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_bool_requests_started_for_run() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=True,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_zero_current_attempt_number() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=0,
            requests_started_for_run=0,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_negative_current_attempt_number() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=-1,
            requests_started_for_run=0,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_requests_started_below_attempt() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=2,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_negative_accumulated_delay() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=-1,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_negative_rate_limit_wait() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=-1,
        )


@pytest.mark.parametrize("delay", (float("nan"), float("inf"), float("-inf")))
def test_context_rejects_non_finite_accumulated_delay(delay: float) -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=delay,
            rate_limit_wait_seconds=0,
        )


@pytest.mark.parametrize("delay", (float("nan"), float("inf"), float("-inf")))
def test_context_rejects_non_finite_rate_limit_wait(delay: float) -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=delay,
        )


def test_context_rejects_bool_delay_fields() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=True,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_string_delay() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds="0",  # type: ignore[arg-type]
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_int_subclass_for_exact_int_fields() -> None:
    """'exact int' excludes int subclasses such as IntEnum, not just bool."""

    class _MyInt(int):
        pass

    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=_MyInt(1),
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=0,
            rate_limit_wait_seconds=0,
        )


def test_context_rejects_float_subclass_for_delay_fields() -> None:
    class _MyFloat(float):
        pass

    with pytest.raises(TypeError):
        ConfluenceRetryEvaluationContext(
            current_attempt_number=1,
            requests_started_for_run=1,
            accumulated_retry_sleep_seconds=_MyFloat(0.0),
            rate_limit_wait_seconds=0,
        )


def test_context_repr_hides_values() -> None:
    context = ConfluenceRetryEvaluationContext(
        current_attempt_number=2,
        requests_started_for_run=5,
        accumulated_retry_sleep_seconds=3.0,
        rate_limit_wait_seconds=1.0,
    )
    rendered = repr(context)
    assert rendered == "ConfluenceRetryEvaluationContext()"
    assert "2" not in rendered
    assert "5" not in rendered


# ---------------------------------------------------------------------------
# C. Outcome-class/stable-kind table
# ---------------------------------------------------------------------------


_RETRYABLE_HTTP_KINDS = (
    ConfluenceRetryStableKind.HTTP_408,
    ConfluenceRetryStableKind.HTTP_429,
    ConfluenceRetryStableKind.HTTP_500,
    ConfluenceRetryStableKind.HTTP_502,
    ConfluenceRetryStableKind.HTTP_503,
    ConfluenceRetryStableKind.HTTP_504,
)
_TERMINAL_HTTP_KINDS = (
    ConfluenceRetryStableKind.HTTP_TERMINAL,
    ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE,
    ConfluenceRetryStableKind.INVALID_HTTP_STATUS,
)
_RETRYABLE_TRANSPORT_KINDS = (
    ConfluenceRetryStableKind.TRANSPORT_TIMEOUT,
    ConfluenceRetryStableKind.CONNECTION_RESET,
    ConfluenceRetryStableKind.CONNECTION_ABORTED,
    ConfluenceRetryStableKind.TEMPORARY_CONNECTION_FAILURE,
    ConfluenceRetryStableKind.TEMPORARY_DNS_FAILURE,
)
_TERMINAL_TRANSPORT_KINDS = (
    ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
    ConfluenceRetryStableKind.PERMANENT_DNS_FAILURE,
    ConfluenceRetryStableKind.TLS_CERTIFICATE_FAILURE,
    ConfluenceRetryStableKind.INVALID_URL,
)
_PAYLOAD_KINDS = (
    ConfluenceRetryStableKind.RESPONSE_TOO_LARGE,
    ConfluenceRetryStableKind.MALFORMED_JSON,
    ConfluenceRetryStableKind.PAYLOAD_VALIDATION_FAILURE,
)
_BUDGET_KINDS = (
    ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED,
    ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY,
    ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED,
    ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
)


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


def _retry_decision(
    outcome_class: ConfluenceRetryOutcomeClass,
    stable_kind: ConfluenceRetryStableKind,
) -> ConfluenceRetryPolicyDecision:
    return ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.RETRY,
        outcome_class=outcome_class,
        stable_kind=stable_kind,
        selected_delay_seconds=1.0,
        next_attempt_number=2,
    )


@pytest.mark.parametrize("stable_kind", _RETRYABLE_HTTP_KINDS)
def test_retryable_http_pairing_accepted(stable_kind: ConfluenceRetryStableKind) -> None:
    _retry_decision(ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE, stable_kind)


@pytest.mark.parametrize("stable_kind", _TERMINAL_HTTP_KINDS)
def test_terminal_http_pairing_accepted(stable_kind: ConfluenceRetryStableKind) -> None:
    _terminate_decision(ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE, stable_kind)


@pytest.mark.parametrize("stable_kind", _RETRYABLE_TRANSPORT_KINDS)
def test_retryable_transport_pairing_accepted(
    stable_kind: ConfluenceRetryStableKind,
) -> None:
    _retry_decision(ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE, stable_kind)


@pytest.mark.parametrize("stable_kind", _TERMINAL_TRANSPORT_KINDS)
def test_terminal_transport_pairing_accepted(
    stable_kind: ConfluenceRetryStableKind,
) -> None:
    _terminate_decision(ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE, stable_kind)


@pytest.mark.parametrize("stable_kind", _PAYLOAD_KINDS)
def test_payload_pairing_accepted(stable_kind: ConfluenceRetryStableKind) -> None:
    _terminate_decision(ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE, stable_kind)


@pytest.mark.parametrize("stable_kind", _BUDGET_KINDS)
def test_budget_pairing_accepted(stable_kind: ConfluenceRetryStableKind) -> None:
    _terminate_decision(ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED, stable_kind)


def test_semantic_observation_with_non_none_stable_kind_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION,
            outcome_class=ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=None,
            next_attempt_number=None,
        )


def test_retryable_outcome_with_terminal_kind_rejected() -> None:
    with pytest.raises(ValueError):
        _retry_decision(
            ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            ConfluenceRetryStableKind.HTTP_TERMINAL,
        )


def test_terminal_outcome_with_retryable_kind_rejected() -> None:
    with pytest.raises(ValueError):
        _terminate_decision(
            ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            ConfluenceRetryStableKind.HTTP_408,
        )


def test_cross_family_kind_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        _retry_decision(
            ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
            ConfluenceRetryStableKind.HTTP_408,
        )


@pytest.mark.parametrize(
    "outcome_class",
    (
        ConfluenceRetryOutcomeClass.SUCCESS,
        ConfluenceRetryOutcomeClass.STATE_FAILURE,
        ConfluenceRetryOutcomeClass.OPERATOR_INTERRUPTION,
    ),
)
def test_unsupported_b2_outcome_classes_rejected(
    outcome_class: ConfluenceRetryOutcomeClass,
) -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.TERMINATE,
            outcome_class=outcome_class,
            stable_kind=None,
            selected_delay_seconds=None,
            next_attempt_number=None,
        )


# ---------------------------------------------------------------------------
# D. Retry-policy decision combinations
# ---------------------------------------------------------------------------


def test_valid_semantic_decision() -> None:
    decision = ConfluenceRetryPolicyDecision(
        action=ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION,
        outcome_class=ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION,
        stable_kind=None,
        selected_delay_seconds=None,
        next_attempt_number=None,
    )
    assert decision.action is ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION


def test_valid_retryable_http_decision() -> None:
    decision = _retry_decision(
        ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_429,
    )
    assert decision.next_attempt_number == 2


def test_valid_retryable_transport_decision() -> None:
    decision = _retry_decision(
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.TRANSPORT_TIMEOUT,
    )
    assert decision.selected_delay_seconds == 1.0


def test_valid_terminal_http_decision() -> None:
    _terminate_decision(
        ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_TERMINAL,
    )


def test_valid_terminal_transport_decision() -> None:
    _terminate_decision(
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
    )


def test_valid_payload_decision() -> None:
    _terminate_decision(
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
        ConfluenceRetryStableKind.MALFORMED_JSON,
    )


def test_valid_budget_decision() -> None:
    _terminate_decision(
        ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
        ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED,
    )


def test_delay_on_terminal_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.TERMINATE,
            outcome_class=ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_TERMINAL,
            selected_delay_seconds=1.0,
            next_attempt_number=None,
        )


def test_missing_delay_on_retry_rejected() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=None,
            next_attempt_number=2,
        )


def test_next_attempt_on_terminal_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.TERMINATE,
            outcome_class=ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_TERMINAL,
            selected_delay_seconds=None,
            next_attempt_number=2,
        )


def test_bool_next_attempt_rejected() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=1.0,
            next_attempt_number=True,
        )


def test_next_attempt_below_two_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=1.0,
            next_attempt_number=1,
        )


@pytest.mark.parametrize("delay", (float("nan"), float("inf")))
def test_non_finite_delay_rejected(delay: float) -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=delay,
            next_attempt_number=2,
        )


def test_negative_delay_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=-1.0,
            next_attempt_number=2,
        )


def test_int_delay_on_retry_rejected() -> None:
    with pytest.raises(TypeError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=1,
            next_attempt_number=2,
        )


def test_retry_decision_rejects_float_subclass_delay() -> None:
    class _MyFloat(float):
        pass

    with pytest.raises(TypeError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=_MyFloat(1.0),
            next_attempt_number=2,
        )


def test_retry_decision_rejects_int_subclass_next_attempt() -> None:
    class _MyInt(int):
        pass

    with pytest.raises(TypeError):
        ConfluenceRetryPolicyDecision(
            action=ConfluenceRetryPolicyAction.RETRY,
            outcome_class=ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
            stable_kind=ConfluenceRetryStableKind.HTTP_408,
            selected_delay_seconds=1.0,
            next_attempt_number=_MyInt(2),
        )


def test_decision_repr_hides_values() -> None:
    decision = _retry_decision(
        ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_408,
    )
    rendered = repr(decision)
    assert rendered == "ConfluenceRetryPolicyDecision()"
    assert "retry" not in rendered
    assert "http_408" not in rendered


def test_decision_equality_is_value_based() -> None:
    first = _retry_decision(
        ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_408,
    )
    second = _retry_decision(
        ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        ConfluenceRetryStableKind.HTTP_408,
    )
    assert first == second


# ---------------------------------------------------------------------------
# E. Request-budget decision combinations
# ---------------------------------------------------------------------------


def test_valid_allow_decision() -> None:
    decision = confluence_request_budget_allow()
    assert decision.action is ConfluenceRequestBudgetAction.ALLOW_ATTEMPT
    assert decision.outcome_class is None
    assert decision.stable_kind is None


def test_valid_budget_termination() -> None:
    decision = confluence_request_budget_terminate()
    assert decision.action is ConfluenceRequestBudgetAction.TERMINATE
    assert decision.outcome_class is ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED
    assert decision.stable_kind is ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED


def test_allow_with_outcome_class_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRequestBudgetDecision(
            action=ConfluenceRequestBudgetAction.ALLOW_ATTEMPT,
            outcome_class=ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
            stable_kind=None,
        )


def test_allow_with_stable_kind_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRequestBudgetDecision(
            action=ConfluenceRequestBudgetAction.ALLOW_ATTEMPT,
            outcome_class=None,
            stable_kind=ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
        )


def test_terminate_without_exact_budget_pair_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRequestBudgetDecision(
            action=ConfluenceRequestBudgetAction.TERMINATE,
            outcome_class=None,
            stable_kind=None,
        )


def test_terminate_with_another_stable_kind_rejected() -> None:
    with pytest.raises(ValueError):
        ConfluenceRequestBudgetDecision(
            action=ConfluenceRequestBudgetAction.TERMINATE,
            outcome_class=ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
            stable_kind=ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED,
        )


def test_request_budget_decision_repr_hides_values() -> None:
    decision = confluence_request_budget_terminate()
    rendered = repr(decision)
    assert rendered == "ConfluenceRequestBudgetDecision()"
    assert "terminate" not in rendered
    assert "request_budget_exhausted" not in rendered
