"""M7-B3 retry and pacing orchestration around the approved B1 transport."""

from __future__ import annotations

import json
import math
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable

from knowledgenexus.foundation.domain.models.confluence_http_outcome import (
    ConfluenceHttpFailureKind,
    ConfluenceHttpFailureMetadata,
    ConfluenceRetryAfterMetadata,
    confluence_retry_after_absent,
)
from knowledgenexus.foundation.domain.models.confluence_retry_policy import (
    ConfluenceRequestBudgetAction,
    ConfluenceRequestBudgetDecision,
    ConfluenceRetryEvaluationContext,
    ConfluenceRetryOutcomeClass,
    ConfluenceRetryPolicyAction,
    ConfluenceRetryPolicyDecision,
    ConfluenceRetryPolicyProfile,
    confluence_request_budget_terminate,
)
from knowledgenexus.foundation.domain.rules.confluence_retry_policy import (
    evaluate_confluence_http_failure,
    evaluate_confluence_request_budget,
    evaluate_confluence_restriction_response,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (
    ConfluenceHttpError,
    ConfluenceHttpResponse,
    UrllibConfluenceHttpTransport,
    prepare_confluence_get_input,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    CheckpointOperationFailure,
    CheckpointOperationFailureCategory,
    CheckpointReservationResult,
    CheckpointStateError,
    ConfluenceCheckpointStatePort,
)


@dataclass(frozen=True, repr=False)
class ConfluenceRetryExecutorProfile:
    retry_policy: ConfluenceRetryPolicyProfile
    minimum_request_interval_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.retry_policy, ConfluenceRetryPolicyProfile):
            raise TypeError("retry_policy expects a ConfluenceRetryPolicyProfile")
        if type(self.minimum_request_interval_seconds) is not float:
            raise TypeError("minimum_request_interval_seconds expects an exact float")
        if self.minimum_request_interval_seconds != 3.0:
            raise ValueError("minimum_request_interval_seconds must equal exactly 3.0")

    @staticmethod
    def from_mapping(mapping: Mapping[str, object]) -> "ConfluenceRetryExecutorProfile":
        policy = ConfluenceRetryPolicyProfile.from_mapping(mapping)
        value = mapping.get("minimum_request_interval_seconds")
        if type(value) is not float or value != 3.0:
            raise ValueError("minimum_request_interval_seconds must equal exactly 3.0")
        return ConfluenceRetryExecutorProfile(policy, value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ConfluenceRetryExecutionSnapshot:
    requests_started_for_run: int
    last_attempt_started_at: int | float | None

    def __post_init__(self) -> None:
        if type(self.requests_started_for_run) is not int:
            raise TypeError("requests_started_for_run expects an exact int")
        if self.requests_started_for_run < 0:
            raise ValueError("requests_started_for_run must be non-negative")
        if self.last_attempt_started_at is not None:
            if type(self.last_attempt_started_at) not in (int, float):
                raise TypeError("last_attempt_started_at expects int, float, or None")
            if isinstance(self.last_attempt_started_at, float) and not math.isfinite(self.last_attempt_started_at):
                raise ValueError("last_attempt_started_at must be finite")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ConfluenceRetryExecutionError(ConfluenceHttpError):
    """Sanitized policy/budget termination with its immutable decision."""

    def __init__(
        self,
        message: str,
        *,
        decision: ConfluenceRequestBudgetDecision | ConfluenceRetryPolicyDecision,
        metadata: ConfluenceHttpFailureMetadata | None = None,
    ) -> None:
        if not isinstance(decision, (ConfluenceRequestBudgetDecision, ConfluenceRetryPolicyDecision)):
            raise TypeError("decision expects a retry-policy decision")
        super().__init__(message, metadata=metadata)
        self._decision = decision

    @property
    def decision(self) -> ConfluenceRequestBudgetDecision | ConfluenceRetryPolicyDecision:
        return self._decision

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ConfluenceStatusAwareExecutionResult:
    response: ConfluenceHttpResponse
    terminal_decision: ConfluenceRetryPolicyDecision | None

    def __post_init__(self) -> None:
        if not isinstance(self.response, ConfluenceHttpResponse):
            raise TypeError("response expects a ConfluenceHttpResponse")
        if self.terminal_decision is not None:
            if not isinstance(self.terminal_decision, ConfluenceRetryPolicyDecision):
                raise TypeError("terminal_decision expects a retry-policy decision")
            if self.terminal_decision.action is not ConfluenceRetryPolicyAction.TERMINATE:
                raise ValueError("terminal_decision must be TERMINATE")
        semantic_status = self.response.status_code in {200, 401, 403, 404}
        if semantic_status and self.terminal_decision is not None:
            raise ValueError("semantic response must not have a terminal decision")
        if not semantic_status and self.terminal_decision is None:
            raise ValueError("non-semantic response requires a terminal decision")
        if self.terminal_decision is not None:
            retryable_status = self.response.status_code in {408, 429, 500, 502, 503, 504}
            expected_class = (
                ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED
                if retryable_status
                else ConfluenceRetryOutcomeClass.TERMINAL_HTTP_FAILURE
            )
            if self.terminal_decision.outcome_class is not expected_class:
                raise ValueError("response status and terminal decision disagree")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


_Clock = Callable[[], int | float]
_Sleeper = Callable[[float], None]


class RetryingConfluenceHttpTransport:
    """Single-worker executor; all HTTP mechanics remain in B1."""

    def __init__(
        self,
        *,
        inner: UrllibConfluenceHttpTransport,
        profile: ConfluenceRetryExecutorProfile,
        monotonic_clock: _Clock,
        sleeper: _Sleeper,
        initial_requests_started_for_run: int = 0,
        attempt_reserver: ConfluenceCheckpointStatePort | None = None,
    ) -> None:
        if not isinstance(inner, UrllibConfluenceHttpTransport):
            raise TypeError("inner expects a UrllibConfluenceHttpTransport")
        if not isinstance(profile, ConfluenceRetryExecutorProfile):
            raise TypeError("profile expects a ConfluenceRetryExecutorProfile")
        if not callable(monotonic_clock) or not callable(sleeper):
            raise TypeError("clock and sleeper must be callable")
        if type(initial_requests_started_for_run) is not int:
            raise TypeError("initial_requests_started_for_run expects an exact int")
        if initial_requests_started_for_run < 0:
            raise ValueError("initial_requests_started_for_run must be non-negative")
        if initial_requests_started_for_run > profile.retry_policy.max_total_requests_per_run:
            raise ValueError("initial_requests_started_for_run must not exceed the profile request limit")
        if attempt_reserver is not None and not callable(
            getattr(attempt_reserver, "reserve_outbound_attempt", None)
        ):
            raise TypeError("attempt_reserver must expose reserve_outbound_attempt")
        if attempt_reserver is not None and not callable(
            getattr(attempt_reserver, "check_outbound_attempt", None)
        ):
            raise TypeError("attempt_reserver must expose check_outbound_attempt")
        self._inner = inner
        self._profile = profile
        self._clock = monotonic_clock
        self._sleeper = sleeper
        self._requests = initial_requests_started_for_run
        self._last_start: int | float | None = None
        self._last_clock: int | float | None = None
        self._attempt_reserver = attempt_reserver
        self._reservation_pending = False

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def snapshot(self) -> ConfluenceRetryExecutionSnapshot:
        return ConfluenceRetryExecutionSnapshot(self._requests, self._last_start)

    @property
    def request_profile_version(self) -> str:
        return "m7-confluence-request-profile-v1"

    @property
    def checkpoint_bound(self) -> bool:
        return self._attempt_reserver is not None

    def _observe_clock(self) -> int | float:
        value = self._clock()
        if type(value) not in (int, float) or isinstance(value, bool):
            raise TypeError("monotonic_clock must return an exact int or float")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("monotonic_clock must return a finite value")
        if self._last_clock is not None and value < self._last_clock:
            raise ValueError("monotonic_clock regression detected")
        self._last_clock = value
        return value

    def _pacing_wait(self, now: int | float) -> float:
        if self._last_start is None:
            return 0.0
        try:
            elapsed = now - self._last_start
        except (OverflowError, TypeError):
            raise ValueError("monotonic_clock values are not comparable") from None
        if elapsed >= self._profile.minimum_request_interval_seconds:
            return 0.0
        remaining = self._profile.minimum_request_interval_seconds - elapsed
        return float(remaining)

    def _budget(self) -> ConfluenceRequestBudgetDecision:
        return evaluate_confluence_request_budget(
            requests_started_for_run=self._requests,
            profile=self._profile.retry_policy,
        )

    def _attempt_start(self) -> None:
        if self._attempt_reserver is not None:
            if not self._reservation_pending:
                raise CheckpointStateError() from None
            self._reservation_pending = False
        decision = self._budget()
        if decision.action is ConfluenceRequestBudgetAction.TERMINATE:
            raise ConfluenceRetryExecutionError("Request budget exhausted", decision=decision)
        start = self._observe_clock()
        self._requests += 1
        self._last_start = start

    def _reserve_attempt(self) -> None:
        if self._attempt_reserver is None:
            return
        result = self._attempt_reserver.reserve_outbound_attempt()
        if isinstance(result, CheckpointOperationFailure):
            if result.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED:
                raise ConfluenceRetryExecutionError(
                    "Request budget exhausted",
                    decision=confluence_request_budget_terminate(),
                )
            raise CheckpointStateError() from None
        if not isinstance(result, CheckpointReservationResult):
            raise CheckpointStateError() from None
        self._reservation_pending = True

    def _preflight_attempt(self) -> None:
        if self._attempt_reserver is None:
            return
        result = self._attempt_reserver.check_outbound_attempt()
        if isinstance(result, CheckpointOperationFailure):
            if result.category is CheckpointOperationFailureCategory.REQUEST_BUDGET_EXHAUSTED:
                raise ConfluenceRetryExecutionError(
                    "Request budget exhausted",
                    decision=confluence_request_budget_terminate(),
                )
            raise CheckpointStateError() from None
        if result is not None:
            raise CheckpointStateError() from None

    def _initial_pacing(self) -> None:
        decision = self._budget()
        if decision.action is ConfluenceRequestBudgetAction.TERMINATE:
            raise ConfluenceRetryExecutionError("Request budget exhausted", decision=decision)
        now = self._observe_clock()
        delay = self._pacing_wait(now)
        if delay > 0.0:
            self._sleeper(delay)

    def _policy_context(self, attempt: int, retry_sleep: float, wait: float) -> ConfluenceRetryEvaluationContext:
        return ConfluenceRetryEvaluationContext(
            current_attempt_number=attempt,
            requests_started_for_run=self._requests,
            accumulated_retry_sleep_seconds=retry_sleep,
            rate_limit_wait_seconds=wait,
        )

    def _retry_after_failure(
        self,
        *,
        error: ConfluenceHttpError,
        attempt: int,
        retry_sleep: float,
    ) -> ConfluenceRetryPolicyDecision:
        context = self._policy_context(attempt, retry_sleep, 0.0)
        decision = evaluate_confluence_http_failure(
            metadata=error.metadata, context=context, profile=self._profile.retry_policy
        )
        if decision.action is not ConfluenceRetryPolicyAction.RETRY:
            return decision
        now = self._observe_clock()
        wait = self._pacing_wait(now)
        return evaluate_confluence_http_failure(
            metadata=error.metadata,
            context=self._policy_context(attempt, retry_sleep, wait),
            profile=self._profile.retry_policy,
        )

    def _retry_after_response(
        self,
        *,
        response: ConfluenceHttpResponse,
        attempt: int,
        retry_sleep: float,
    ) -> ConfluenceRetryPolicyDecision:
        decision = evaluate_confluence_restriction_response(
            status_code=response.status_code,
            retry_after=response.retry_after,
            context=self._policy_context(attempt, retry_sleep, 0.0),
            profile=self._profile.retry_policy,
        )
        if decision.action is not ConfluenceRetryPolicyAction.RETRY:
            return decision
        now = self._observe_clock()
        return evaluate_confluence_restriction_response(
            status_code=response.status_code,
            retry_after=response.retry_after,
            context=self._policy_context(attempt, retry_sleep, self._pacing_wait(now)),
            profile=self._profile.retry_policy,
        )

    def _sleep_or_raise(
        self,
        decision: ConfluenceRetryPolicyDecision,
        *,
        metadata: ConfluenceHttpFailureMetadata | None,
        retry_sleep: float,
    ) -> float:
        if decision.action is not ConfluenceRetryPolicyAction.RETRY:
            if decision.outcome_class is ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED:
                raise ConfluenceRetryExecutionError("Retry policy exhausted", decision=decision, metadata=metadata)
            return retry_sleep
        budget = self._budget()
        if budget.action is ConfluenceRequestBudgetAction.TERMINATE:
            raise ConfluenceRetryExecutionError("Request budget exhausted", decision=budget, metadata=metadata)
        delay = decision.selected_delay_seconds or 0.0
        if delay > 0.0:
            self._sleeper(delay)
            retry_sleep += delay
        return retry_sleep

    def _prepare_request(
        self, *, path: str, query: Mapping[str, str]
    ) -> urllib.request.Request:
        prepared = prepare_confluence_get_input(path=path, query=query)
        return self._inner._build_request_prepared(prepared)

    def _read_body(
        self, request: urllib.request.Request, callback: Callable[[], None]
    ) -> bytes:
        return self._inner._read_response_bytes_request(
            request, on_attempt_start=callback
        )

    @staticmethod
    def _parse_json(body: bytes) -> Mapping[str, object]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ConfluenceHttpError(
                "Confluence GET returned malformed JSON",
                metadata=ConfluenceHttpFailureMetadata(
                    kind=ConfluenceHttpFailureKind.MALFORMED_JSON,
                    http_status=None,
                    retry_after=confluence_retry_after_absent(),
                ),
            ) from None
        if not isinstance(payload, Mapping):
            raise ConfluenceHttpError(
                "Confluence GET returned a non-object JSON payload",
                metadata=ConfluenceHttpFailureMetadata(
                    kind=ConfluenceHttpFailureKind.PAYLOAD_VALIDATION_FAILURE,
                    http_status=None,
                    retry_after=confluence_retry_after_absent(),
                ),
            )
        return payload

    def get_json(self, *, path: str, query: Mapping[str, str]) -> Mapping[str, object]:
        request = self._prepare_request(path=path, query=query)
        self._preflight_attempt()
        self._initial_pacing()
        self._reserve_attempt()
        attempt, retry_sleep = 1, 0.0
        while True:
            try:
                body = self._read_body(request, self._attempt_start)
                return self._parse_json(body)
            except ConfluenceRetryExecutionError:
                raise
            except ConfluenceHttpError as error:
                decision = self._retry_after_failure(error=error, attempt=attempt, retry_sleep=retry_sleep)
                if decision.action is ConfluenceRetryPolicyAction.TERMINATE and decision.outcome_class is not ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED:
                    raise
                self._preflight_attempt()
                retry_sleep = self._sleep_or_raise(decision, metadata=error.metadata, retry_sleep=retry_sleep)
                self._reserve_attempt()
                attempt = decision.next_attempt_number or attempt

    def get_bytes(self, *, path: str, query: Mapping[str, str]) -> bytes:
        request = self._prepare_request(path=path, query=query)
        self._preflight_attempt()
        self._initial_pacing()
        self._reserve_attempt()
        attempt, retry_sleep = 1, 0.0
        while True:
            try:
                return self._read_body(request, self._attempt_start)
            except ConfluenceRetryExecutionError:
                raise
            except ConfluenceHttpError as error:
                decision = self._retry_after_failure(error=error, attempt=attempt, retry_sleep=retry_sleep)
                if decision.action is ConfluenceRetryPolicyAction.TERMINATE and decision.outcome_class is not ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED:
                    raise
                self._preflight_attempt()
                retry_sleep = self._sleep_or_raise(decision, metadata=error.metadata, retry_sleep=retry_sleep)
                self._reserve_attempt()
                attempt = decision.next_attempt_number or attempt

    def get_response_bytes(self, *, path: str, query: Mapping[str, str]) -> ConfluenceHttpResponse:
        return self.get_response_bytes_result(path=path, query=query).response

    def get_response_bytes_result(self, *, path: str, query: Mapping[str, str]) -> ConfluenceStatusAwareExecutionResult:
        request = self._prepare_request(path=path, query=query)
        self._preflight_attempt()
        self._initial_pacing()
        self._reserve_attempt()
        attempt, retry_sleep = 1, 0.0
        while True:
            try:
                response = self._inner._get_response_bytes_request(
                    request, on_attempt_start=self._attempt_start
                )
            except ConfluenceRetryExecutionError:
                raise
            except ConfluenceHttpError as error:
                decision = self._retry_after_failure(error=error, attempt=attempt, retry_sleep=retry_sleep)
                if decision.action is ConfluenceRetryPolicyAction.TERMINATE and decision.outcome_class is not ConfluenceRetryOutcomeClass.BUDGET_EXHAUSTED:
                    raise
                self._preflight_attempt()
                retry_sleep = self._sleep_or_raise(decision, metadata=error.metadata, retry_sleep=retry_sleep)
                self._reserve_attempt()
                attempt = decision.next_attempt_number or attempt
                continue

            decision = self._retry_after_response(response=response, attempt=attempt, retry_sleep=retry_sleep)
            if decision.action is ConfluenceRetryPolicyAction.ACCEPT_SEMANTIC_OBSERVATION:
                return ConfluenceStatusAwareExecutionResult(response=response, terminal_decision=None)
            if decision.action is ConfluenceRetryPolicyAction.TERMINATE:
                return ConfluenceStatusAwareExecutionResult(response=response, terminal_decision=decision)
            metadata = ConfluenceHttpFailureMetadata(
                kind=ConfluenceHttpFailureKind.HTTP_STATUS,
                http_status=response.status_code,
                retry_after=response.retry_after,
            )
            self._preflight_attempt()
            retry_sleep = self._sleep_or_raise(decision, metadata=metadata, retry_sleep=retry_sleep)
            self._reserve_attempt()
            attempt = decision.next_attempt_number or attempt


__all__ = [
    "ConfluenceRetryExecutorProfile",
    "ConfluenceRetryExecutionError",
    "ConfluenceRetryExecutionSnapshot",
    "ConfluenceStatusAwareExecutionResult",
    "RetryingConfluenceHttpTransport",
]
