from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


# The single owner-approved profile-v1 mapping (owner decision L / M7-A2
# `crawl_reliability_profile.yaml`). Profile version "1" is bound to exactly
# this mapping; there is no general-purpose profile-v1 constructor. The
# mapping is a read-only proxy so the approved binding cannot be rebound at
# runtime, which would otherwise silently redefine what "approved" means.
_EXPECTED_PROFILE_V1: Mapping[str, object] = MappingProxyType({
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
})

_PROFILE_V1_STR_KEYS = ("profile_id", "profile_version")
_PROFILE_V1_BOOL_KEYS = ("jitter",)
_PROFILE_V1_FLOAT_KEYS = (
    "minimum_request_interval_seconds",
    "base_backoff_seconds",
    "max_retry_delay_seconds",
    "max_total_retry_delay_seconds",
)
_PROFILE_V1_INT_KEYS = tuple(
    key
    for key in _EXPECTED_PROFILE_V1
    if key
    not in _PROFILE_V1_STR_KEYS + _PROFILE_V1_BOOL_KEYS + _PROFILE_V1_FLOAT_KEYS
)

_B2_PROJECTION_FIELDS = (
    "profile_id",
    "profile_version",
    "max_total_requests_per_run",
    "max_attempts",
    "base_backoff_seconds",
    "max_retry_delay_seconds",
    "max_total_retry_delay_seconds",
    "jitter",
)


def _validate_confluence_retry_profile_v1_binding(
    profile_mapping: object,
) -> Mapping[str, object]:
    """Validate the complete exact profile-v1 binding without mutating input."""

    if not isinstance(profile_mapping, Mapping):
        raise ValueError("reliability profile binding failed: expected a mapping")

    actual_keys = set(profile_mapping.keys())
    expected_keys = set(_EXPECTED_PROFILE_V1.keys())

    missing_keys = expected_keys - actual_keys
    if missing_keys:
        raise ValueError(
            f"reliability profile key '{sorted(missing_keys)[0]}' is missing"
        )
    if actual_keys - expected_keys:
        # An unapproved key name is arbitrary caller-supplied data, so it is
        # reported as the general binding failure rather than echoed.
        raise ValueError(
            "reliability profile binding failed: an unapproved key is present "
            "under profile_version '1'"
        )

    for key in _PROFILE_V1_STR_KEYS:
        if type(profile_mapping[key]) is not str:
            raise ValueError(f"reliability profile key '{key}' has an invalid type")
    for key in _PROFILE_V1_BOOL_KEYS:
        if type(profile_mapping[key]) is not bool:
            raise ValueError(f"reliability profile key '{key}' has an invalid type")
    for key in _PROFILE_V1_FLOAT_KEYS:
        if type(profile_mapping[key]) is not float:
            raise ValueError(f"reliability profile key '{key}' has an invalid type")
    for key in _PROFILE_V1_INT_KEYS:
        if type(profile_mapping[key]) is not int:
            raise ValueError(f"reliability profile key '{key}' has an invalid type")

    for key, expected_value in _EXPECTED_PROFILE_V1.items():
        if profile_mapping[key] != expected_value:
            raise ValueError(f"reliability profile key '{key}' has an unexpected value")

    return profile_mapping


@dataclass(frozen=True, repr=False)
class ConfluenceRetryPolicyProfile:
    """The pinned B2 projection of the approved `m7-crawl-reliability-v1` profile.

    Profile version "1" has exactly one approved value set; there is no
    general-purpose constructor for arbitrary version-1 values, so every
    field is re-validated against the approved binding regardless of
    construction path.
    """

    profile_id: str
    profile_version: str
    max_total_requests_per_run: int
    max_attempts: int
    base_backoff_seconds: float
    max_retry_delay_seconds: float
    max_total_retry_delay_seconds: float
    jitter: bool

    def __post_init__(self) -> None:
        for field_name in _B2_PROJECTION_FIELDS:
            actual = getattr(self, field_name)
            expected = _EXPECTED_PROFILE_V1[field_name]
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError(
                    "ConfluenceRetryPolicyProfile field does not match the "
                    "approved profile-v1 projection"
                )

    @staticmethod
    def from_mapping(
        profile_mapping: Mapping[str, object],
    ) -> "ConfluenceRetryPolicyProfile":
        validated = _validate_confluence_retry_profile_v1_binding(profile_mapping)
        return ConfluenceRetryPolicyProfile(
            profile_id=validated["profile_id"],
            profile_version=validated["profile_version"],
            max_total_requests_per_run=validated["max_total_requests_per_run"],
            max_attempts=validated["max_attempts"],
            base_backoff_seconds=validated["base_backoff_seconds"],
            max_retry_delay_seconds=validated["max_retry_delay_seconds"],
            max_total_retry_delay_seconds=validated["max_total_retry_delay_seconds"],
            jitter=validated["jitter"],
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _require_exact_int(field_name: str, value: object) -> None:
    # Exact type, so bool and any int subclass (IntEnum, numpy ints) are
    # rejected rather than silently coerced.
    if type(value) is not int:
        raise TypeError(f"{field_name} expects an exact int")


def _require_finite_non_negative_delay(field_name: str, value: object) -> None:
    if type(value) not in (int, float):
        raise TypeError(f"{field_name} expects an exact int or float")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True, repr=False)
class ConfluenceRetryEvaluationContext:
    """Immutable caller/state facts an evaluator needs; profile-agnostic."""

    current_attempt_number: int
    requests_started_for_run: int
    accumulated_retry_sleep_seconds: int | float
    rate_limit_wait_seconds: int | float

    def __post_init__(self) -> None:
        _require_exact_int(
            "current_attempt_number", self.current_attempt_number
        )
        _require_exact_int(
            "requests_started_for_run", self.requests_started_for_run
        )
        if self.current_attempt_number < 1:
            raise ValueError("current_attempt_number must be >= 1")
        if self.requests_started_for_run < self.current_attempt_number:
            raise ValueError(
                "requests_started_for_run must be >= current_attempt_number"
            )
        _require_finite_non_negative_delay(
            "accumulated_retry_sleep_seconds",
            self.accumulated_retry_sleep_seconds,
        )
        _require_finite_non_negative_delay(
            "rate_limit_wait_seconds", self.rate_limit_wait_seconds
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ConfluenceRetryOutcomeClass(str, Enum):
    """The complete approved M7-A2 outcome-class taxonomy."""

    SUCCESS = "success"
    SEMANTIC_OBSERVATION = "semantic_observation"
    RETRYABLE_HTTP_FAILURE = "retryable_http_failure"
    TERMINAL_HTTP_FAILURE = "terminal_http_failure"
    RETRYABLE_TRANSPORT_FAILURE = "retryable_transport_failure"
    TERMINAL_TRANSPORT_FAILURE = "terminal_transport_failure"
    PAYLOAD_FAILURE = "payload_failure"
    STATE_FAILURE = "state_failure"
    OPERATOR_INTERRUPTION = "operator_interruption"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ConfluenceRetryStableKind(str, Enum):
    """The stable failure/terminal kind subset emitted by pure M7-B2 policy."""

    HTTP_408 = "http_408"
    HTTP_429 = "http_429"
    HTTP_500 = "http_500"
    HTTP_502 = "http_502"
    HTTP_503 = "http_503"
    HTTP_504 = "http_504"
    HTTP_TERMINAL = "http_terminal"
    REDIRECT_POLICY_FAILURE = "redirect_policy_failure"
    INVALID_HTTP_STATUS = "invalid_http_status"

    TRANSPORT_TIMEOUT = "transport_timeout"
    CONNECTION_RESET = "connection_reset"
    CONNECTION_ABORTED = "connection_aborted"
    TEMPORARY_CONNECTION_FAILURE = "temporary_connection_failure"
    TEMPORARY_DNS_FAILURE = "temporary_dns_failure"

    UNCLASSIFIED_OS_ERROR = "unclassified_os_error"
    PERMANENT_DNS_FAILURE = "permanent_dns_failure"
    TLS_CERTIFICATE_FAILURE = "tls_certificate_failure"
    INVALID_URL = "invalid_url"

    RESPONSE_TOO_LARGE = "response_too_large"
    MALFORMED_JSON = "malformed_json"
    PAYLOAD_VALIDATION_FAILURE = "payload_validation_failure"

    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    RETRY_AFTER_EXCEEDS_POLICY = "retry_after_exceeds_policy"
    RETRY_DELAY_BUDGET_EXHAUSTED = "retry_delay_budget_exhausted"
    REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"


class ConfluenceRetryPolicyAction(str, Enum):
    ACCEPT_SEMANTIC_OBSERVATION = "accept_semantic_observation"
    RETRY = "retry"
    TERMINATE = "terminate"


# Section 9: the normative and exhaustive outcome-class/stable-kind binding.
# SEMANTIC_OBSERVATION is handled separately (its stable_kind must be None).
_OUTCOME_CLASS_STABLE_KINDS: Mapping[
    ConfluenceRetryOutcomeClass, frozenset[ConfluenceRetryStableKind]
] = MappingProxyType({
    ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE: frozenset(
        {
            ConfluenceRetryStableKind.HTTP_408,
            ConfluenceRetryStableKind.HTTP_429,
            ConfluenceRetryStableKind.HTTP_500,
            ConfluenceRetryStableKind.HTTP_502,
            ConfluenceRetryStableKind.HTTP_503,
            ConfluenceRetryStableKind.HTTP_504,
        }
    ),
    ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE: frozenset(
        {
            ConfluenceRetryStableKind.HTTP_TERMINAL,
            ConfluenceRetryStableKind.REDIRECT_POLICY_FAILURE,
            ConfluenceRetryStableKind.INVALID_HTTP_STATUS,
        }
    ),
    ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE: frozenset(
        {
            ConfluenceRetryStableKind.TRANSPORT_TIMEOUT,
            ConfluenceRetryStableKind.CONNECTION_RESET,
            ConfluenceRetryStableKind.CONNECTION_ABORTED,
            ConfluenceRetryStableKind.TEMPORARY_CONNECTION_FAILURE,
            ConfluenceRetryStableKind.TEMPORARY_DNS_FAILURE,
        }
    ),
    ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE: frozenset(
        {
            ConfluenceRetryStableKind.UNCLASSIFIED_OS_ERROR,
            ConfluenceRetryStableKind.PERMANENT_DNS_FAILURE,
            ConfluenceRetryStableKind.TLS_CERTIFICATE_FAILURE,
            ConfluenceRetryStableKind.INVALID_URL,
        }
    ),
    ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE: frozenset(
        {
            ConfluenceRetryStableKind.RESPONSE_TOO_LARGE,
            ConfluenceRetryStableKind.MALFORMED_JSON,
            ConfluenceRetryStableKind.PAYLOAD_VALIDATION_FAILURE,
        }
    ),
    ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED: frozenset(
        {
            ConfluenceRetryStableKind.ATTEMPTS_EXHAUSTED,
            ConfluenceRetryStableKind.RETRY_AFTER_EXCEEDS_POLICY,
            ConfluenceRetryStableKind.RETRY_DELAY_BUDGET_EXHAUSTED,
            ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
        }
    ),
})

_RETRYABLE_OUTCOME_CLASSES = frozenset(
    {
        ConfluenceRetryOutcomeClass.RETRYABLE_HTTP_FAILURE,
        ConfluenceRetryOutcomeClass.RETRYABLE_TRANSPORT_FAILURE,
    }
)

_TERMINATE_OUTCOME_CLASSES = frozenset(
    {
        ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE,
        ConfluenceRetryOutcomeClass.TERMINAL_TRANSPORT_FAILURE,
        ConfluenceRetryOutcomeClass.PAYLOAD_FAILURE,
        ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
    }
)


def _validate_outcome_stable_kind_pair(
    outcome_class: ConfluenceRetryOutcomeClass,
    stable_kind: ConfluenceRetryStableKind | None,
) -> None:
    if outcome_class is ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION:
        if stable_kind is not None:
            raise ValueError("SEMANTIC_OBSERVATION requires stable_kind is None")
        return

    allowed = _OUTCOME_CLASS_STABLE_KINDS.get(outcome_class)
    if allowed is None:
        raise ValueError(
            f"{outcome_class.value} is not a valid B2 decision outcome class"
        )
    if stable_kind not in allowed:
        raise ValueError(
            f"stable_kind is not valid for outcome class {outcome_class.value}"
        )


@dataclass(frozen=True, repr=False)
class ConfluenceRetryPolicyDecision:
    """One immutable retry-policy decision; never a delay/attempt mutation."""

    action: ConfluenceRetryPolicyAction
    outcome_class: ConfluenceRetryOutcomeClass
    stable_kind: ConfluenceRetryStableKind | None
    selected_delay_seconds: float | None
    next_attempt_number: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ConfluenceRetryPolicyAction):
            raise TypeError("action expects a ConfluenceRetryPolicyAction")
        if not isinstance(self.outcome_class, ConfluenceRetryOutcomeClass):
            raise TypeError("outcome_class expects a ConfluenceRetryOutcomeClass")
        if self.stable_kind is not None and not isinstance(
            self.stable_kind, ConfluenceRetryStableKind
        ):
            raise TypeError("stable_kind expects a ConfluenceRetryStableKind or None")

        _validate_outcome_stable_kind_pair(self.outcome_class, self.stable_kind)

        if self.action is ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION:
            if self.outcome_class is not ConfluenceRetryOutcomeClass.SEMANTIC_OBSERVATION:
                raise ValueError(
                    "ACCEPT_SEMANTIC_OBSERVATION requires SEMANTIC_OBSERVATION"
                )
            if self.selected_delay_seconds is not None:
                raise ValueError(
                    "ACCEPT_SEMANTIC_OBSERVATION requires selected_delay_seconds "
                    "is None"
                )
            if self.next_attempt_number is not None:
                raise ValueError(
                    "ACCEPT_SEMANTIC_OBSERVATION requires next_attempt_number "
                    "is None"
                )
            return

        if self.action is ConfluenceRetryPolicyAction.RETRY:
            if self.outcome_class not in _RETRYABLE_OUTCOME_CLASSES:
                raise ValueError("RETRY requires a retryable outcome class")
            if type(self.selected_delay_seconds) is not float:
                raise TypeError("RETRY requires an exact float selected_delay_seconds")
            if not math.isfinite(self.selected_delay_seconds):
                raise ValueError("selected_delay_seconds must be finite")
            if self.selected_delay_seconds < 0:
                raise ValueError("selected_delay_seconds must be non-negative")
            if type(self.next_attempt_number) is not int:
                raise TypeError("RETRY requires an exact int next_attempt_number")
            if self.next_attempt_number < 2:
                raise ValueError("next_attempt_number must be >= 2")
            return

        # action is TERMINATE (the only remaining ConfluenceRetryPolicyAction).
        if self.outcome_class not in _TERMINATE_OUTCOME_CLASSES:
            raise ValueError(
                "TERMINATE requires a terminal or budget-exhausted outcome class"
            )
        if self.selected_delay_seconds is not None:
            raise ValueError("TERMINATE requires selected_delay_seconds is None")
        if self.next_attempt_number is not None:
            raise ValueError("TERMINATE requires next_attempt_number is None")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ConfluenceRequestBudgetAction(str, Enum):
    ALLOW_ATTEMPT = "allow_attempt"
    TERMINATE = "terminate"


@dataclass(frozen=True, repr=False)
class ConfluenceRequestBudgetDecision:
    """One immutable request-budget preflight decision.

    Exactly two valid states exist; there is no selected delay, next attempt,
    remaining budget, counter, or mutable reservation on this model.
    """

    action: ConfluenceRequestBudgetAction
    outcome_class: ConfluenceRetryOutcomeClass | None
    stable_kind: ConfluenceRetryStableKind | None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ConfluenceRequestBudgetAction):
            raise TypeError("action expects a ConfluenceRequestBudgetAction")
        if self.outcome_class is not None and not isinstance(
            self.outcome_class, ConfluenceRetryOutcomeClass
        ):
            raise TypeError(
                "outcome_class expects a ConfluenceRetryOutcomeClass or None"
            )
        if self.stable_kind is not None and not isinstance(
            self.stable_kind, ConfluenceRetryStableKind
        ):
            raise TypeError("stable_kind expects a ConfluenceRetryStableKind or None")

        if self.action is ConfluenceRequestBudgetAction.ALLOW_ATTEMPT:
            if self.outcome_class is not None:
                raise ValueError("ALLOW_ATTEMPT requires outcome_class is None")
            if self.stable_kind is not None:
                raise ValueError("ALLOW_ATTEMPT requires stable_kind is None")
            return

        # action is TERMINATE (the only other ConfluenceRequestBudgetAction).
        if self.outcome_class is not ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED:
            raise ValueError("TERMINATE requires outcome_class BUDGET_EXHAUSTED")
        if self.stable_kind is not ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED:
            raise ValueError(
                "TERMINATE requires stable_kind REQUEST_BUDGET_EXHAUSTED"
            )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def confluence_request_budget_allow() -> ConfluenceRequestBudgetDecision:
    return ConfluenceRequestBudgetDecision(
        action=ConfluenceRequestBudgetAction.ALLOW_ATTEMPT,
        outcome_class=None,
        stable_kind=None,
    )


def confluence_request_budget_terminate() -> ConfluenceRequestBudgetDecision:
    return ConfluenceRequestBudgetDecision(
        action=ConfluenceRequestBudgetAction.TERMINATE,
        outcome_class=ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED,
        stable_kind=ConfluenceRetryStableKind.REQUEST_BUDGET_EXHAUSTED,
    )
