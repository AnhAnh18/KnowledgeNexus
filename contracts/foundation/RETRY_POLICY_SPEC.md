# Confluence Crawl Retry Policy Specification (M7-A2)

## 1. Status, authority, and precedence

Status: M7-A2 contract complete and owner-approved.

```text
M7-A1: OWNER-APPROVED
M7-A1 independent review: WAIVED BY OWNER
M7-A2: COMPLETE AND APPROVED
M7-A3a/A3b/A3c: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

The schemas in `contracts/foundation/schemas/` win every field-level dispute.
This specification is an active focused specification beside
`CRAWL_RELIABILITY_SPEC.md`. It narrows owner decision I in
`decision_logs/M7_OWNER_DECISIONS.md` and is authoritative for M7-v1 request
outcome classification, retry eligibility, attempts, delay selection, and
request-budget accounting.

The machine-readable numeric source is
`crawl_reliability_profile.yaml`. Its values MUST exactly match owner decision
L. A mismatch is a contract defect; neither source silently overrides the
other. Changing a locked value requires a new `profile_version`, a new crawl
fingerprint, and explicit owner approval.

This document defines future behavior only. It authorizes no production code,
network request, live execution, or credential use.

## 2. Purpose and non-goals

The purpose of M7-A2 is to make the result of every future bounded, read-only
Confluence crawl request deterministic and deny-safe while preventing
unbounded retries, sleeps, or requests.

M7-A2 does not:

- implement a transport, retry executor, clock, sleeper, or rate limiter;
- change existing M5/M6 transport or adapter behavior;
- implement checkpoint persistence, SQLite, raw-generation storage, file
  locking, crawl orchestration, controlled stop, or publication;
- authorize retries for filesystem/database mutation, export, publication, or
  any non-idempotent HTTP operation;
- add or change a Foundation JSON Schema;
- authorize a separately gated M7-C or later production implementation.

## 3. Applicability

This policy applies only to bounded read-only HTTP `GET` request profiles used
by Foundation Confluence crawl acquisition. A request profile MUST be
explicitly approved as read-only and idempotent before it may use this policy.

Publication, raw-store mutation, checkpoint mutation, export, and database
mutation are outside the HTTP retry executor. Failure after an HTTP response
has moved into parsing, validation, raw publication, or checkpoint processing
MUST NOT restart the HTTP request through this policy.

## 4. Terminology

- **Request kind** — an allowlisted crawl operation such as inventory, page,
  restriction, or attachment-metadata acquisition.
- **Attempt** — an outbound request that actually starts. An attempt consumes
  one unit of the run request budget.
- **Initial attempt** — attempt 1.
- **Retry ordinal** — one-based ordinal of the delay before a retry. Retry
  ordinal 1 precedes attempt 2.
- **Client backoff** — deterministic exponential delay selected from the
  profile.
- **Retry-After delay** — a valid server-requested delay derived without
  retaining or exposing the raw field value.
- **Rate-limit wait** — delay required to satisfy the configured minimum
  request interval at the time the next attempt would begin.
- **Actual retry sleep** — the single selected sleep before one retry attempt.
- **Terminal** — no retry sleep and no further request for that logical
  request.
- **Failure kind** — stable sanitized internal reason; never a raw exception
  class or message.
- **Outcome class** — one of the ten classes in §5.

## 5. Complete failure taxonomy

Every completed request-policy evaluation MUST resolve to exactly one of these
outcome classes:

1. `success`
2. `semantic_observation`
3. `retryable_http_failure`
4. `terminal_http_failure`
5. `retryable_transport_failure`
6. `terminal_transport_failure`
7. `payload_failure`
8. `state_failure`
9. `operator_interruption`
10. `budget_exhausted`

The stable failure/terminal kinds are:

| Outcome class | Allowed stable kinds |
| --- | --- |
| `retryable_http_failure` | `http_408`, `http_429`, `http_500`, `http_502`, `http_503`, `http_504` |
| `terminal_http_failure` | `http_terminal`, `redirect_policy_failure`, `invalid_http_status` |
| `retryable_transport_failure` | `transport_timeout`, `connection_reset`, `connection_aborted`, `temporary_connection_failure`, `temporary_dns_failure` |
| `terminal_transport_failure` | `unclassified_os_error`, `permanent_dns_failure`, `tls_certificate_failure`, `invalid_url` |
| `payload_failure` | `response_too_large`, `malformed_json`, `payload_validation_failure`, `identity_mismatch` |
| `state_failure` | `state_conflict`, `checkpoint_failure`, `raw_store_failure` |
| `budget_exhausted` | `attempts_exhausted`, `retry_after_exceeds_policy`, `retry_delay_budget_exhausted`, `request_budget_exhausted`, `inventory_page_budget_exhausted` |

`success` and `semantic_observation` carry no failure kind.
`operator_interruption` documents the disposition of the three BaseException
types in §15; the retry executor MUST NOT catch or convert those exceptions
into a returned outcome.

There is no generic status-range retry and no generic exception retry.
Unknown or unclassified failures are terminal, never retryable by default.

## 6. HTTP status classification

Exactly these HTTP statuses are retryable:

```text
408
429
500
502
503
504
```

No other HTTP status is retryable. The implementation MUST use exact status
membership, not a generic `4xx` or `5xx` rule.

An approved success status proceeds to request-specific parsing and identity
validation. It becomes `success` only after those required steps succeed.
Every non-retryable status not defined as a request-specific semantic outcome
is `terminal_http_failure/http_terminal`.

Redirect outcomes are always
`terminal_http_failure/redirect_policy_failure`. A redirect MUST NOT be
followed or converted into a semantic observation.

## 7. Restriction semantic observations

For the approved Confluence view-restriction request kind, exactly these
statuses are semantic observations:

```text
200
401
403
404
```

They are interpreted only through the active ACL/restriction contract. They
are not generic successes or retry failures.

For a restriction request, `408`, `429`, `500`, `502`, `503`, and `504` remain
operational retryable HTTP failures. They MUST NOT be materialized as ACL
observations. All other statuses are terminal unless another active focused
request contract explicitly defines that status as a semantic outcome.

This future classification is additive M7 behavior. M7-A2 does not change the
current M6B adapter, which presently preserves an unexpected restriction body
before failing operationally.

## 8. Typed transport failure classification

Exactly these typed transport failure kinds are retryable:

```text
transport_timeout
connection_reset
connection_aborted
temporary_connection_failure
temporary_dns_failure
```

The future structured transport boundary MUST classify a failure from typed,
reviewed facts. It MUST NOT make every `OSError`, `Exception`, or unknown
transport failure retryable.

At minimum these transport/internal kinds are terminal:

```text
unclassified_os_error
permanent_dns_failure
tls_certificate_failure
redirect_policy_failure
invalid_url
response_too_large
malformed_json
payload_validation_failure
identity_mismatch
state_conflict
checkpoint_failure
raw_store_failure
```

Payload parsing, source-identity validation, raw publication, checkpoint
storage, and state conflict occur outside the HTTP retry executor. They MUST
NOT trigger another HTTP attempt.

## 9. Attempt accounting

`max_attempts` includes the initial attempt. With the locked value `4`:

```text
attempt 1 = initial attempt
attempt 2 = retry 1
attempt 3 = retry 2
attempt 4 = retry 3
```

An attempt counts only when the outbound request actually starts. A blocked
request that fails a budget check before outbound I/O is not an attempt.

M7-C durable request-budget reservation is a separate, more conservative
cross-session accounting unit. A committed reservation that is followed by a
process crash before outbound I/O consumes one budget unit without becoming an
actual outbound attempt. This exception applies only to durable run-budget
accounting; it does not alter `max_attempts` accounting for one logical request.

After attempt 4 fails, the result is
`budget_exhausted/attempts_exhausted`. There is no retry sleep and no fifth
request.

## 10. Deterministic backoff

Retry ordinal starts at 1 for the delay before attempt 2:

```text
client_backoff = min(
    max_retry_delay_seconds,
    base_backoff_seconds * 2 ** (retry_ordinal - 1),
)
```

For the locked profile the retry backoffs are exactly `1.0`, `2.0`, and
`4.0` seconds before attempts 2, 3, and 4. Jitter is disabled. Adding jitter
requires a new reviewed contract and an injected deterministic source.

## 11. Retry-After parsing

The future response metadata boundary may expose only a typed sanitized
Retry-After parse result. The raw field value MUST NOT be logged, persisted in
checkpoint state, included in durable evidence, or exposed by `str`/`repr`.

Accepted forms:

- one complete non-negative decimal delta-seconds value;
- one valid HTTP-date interpreted using an injected UTC clock.

Rules:

- a future HTTP-date yields `date - injected_utc_now`;
- a past HTTP-date yields zero;
- invalid, negative, duplicate, or ambiguous values are ignored;
- an HTTP-date MUST NOT be split on commas as though it were a list;
- ignored Retry-After input contributes zero and falls back to client
  backoff/rate-limit wait;
- a valid delay equal to `max_retry_delay_seconds` is allowed;
- a valid delay greater than `max_retry_delay_seconds` terminates with
  `budget_exhausted/retry_after_exceeds_policy`;
- an oversized valid delay is never clamped downward, causes no sleep, and
  causes no further request.

Parsing MUST consume the complete field representation. A decimal parser MUST
not accept signs, fractions, units, or trailing data. Duplicate field
instances or a combined representation that is ambiguous are ignored as one
invalid Retry-After input; implementations MUST NOT select the first value.

## 12. Rate-limit interaction and one selected sleep

For one retry:

```text
retry_component = max(
    client_backoff,
    valid_retry_after_or_zero,
)

actual_retry_sleep = max(
    rate_limit_wait,
    retry_component,
)
```

There is exactly one selected sleep before one retry attempt. Components are
not slept separately and are not summed.

`rate_limit_wait` MUST be computed against an injected monotonic clock from
the last actual outbound attempt. Normal pacing before the initial attempt is
not retry delay; it is tracked separately in the total crawl/runtime budget.

## 13. Single-delay and total-delay budgets

Before sleeping, the policy MUST apply these checks in order:

1. If a valid Retry-After exceeds `max_retry_delay_seconds`, terminate with
   `retry_after_exceeds_policy`.
2. Compute `actual_retry_sleep` according to §12.
3. If `actual_retry_sleep > max_retry_delay_seconds`, terminate with
   `retry_delay_budget_exhausted`.
4. If `accumulated_retry_sleep + actual_retry_sleep >
   max_total_retry_delay_seconds`, terminate with
   `retry_delay_budget_exhausted`.

Equality with either limit is allowed.

The accumulated retry-delay budget is the sum of actual sleeps before retry
attempts. It is not the sum of the backoff, Retry-After, and rate-limit
components. If a required delay exceeds a budget, the policy performs no
sleep and starts no further request.

No sleep occurs after the final allowed attempt.

## 14. Total request-budget accounting

Every actual outbound attempt, including retries, requires one unit from
`max_total_requests_per_run`.

For M7-C, the authoritative cross-session unit is reserved durably immediately
before outbound I/O. Every actual outbound attempt follows one reservation, but
a committed reservation may conservatively remain consumed after a crash before
the request starts. Reservations are never refunded.

The request budget MUST be checked immediately before an outbound attempt
starts. When no unit remains:

- no outbound request starts;
- no attempt is counted;
- the logical request terminates with
  `budget_exhausted/request_budget_exhausted`.

This applies before the initial attempt and before every retry. A selected
retry sleep MUST NOT occur when it is already known that no request-budget
unit remains for the following attempt.

The M7-C retry integration performs a non-mutating durable-capacity check before
such a retry sleep, then invokes the durable reservation seam immediately before
the B1 outbound-start boundary. B3 retains retry selection, pacing, and attempt
loop ownership; it does not access checkpoint storage.

## 15. Operator interruption

The retry executor MUST NOT catch, convert, classify as unexpected, log, or
retry:

```text
KeyboardInterrupt
SystemExit
GeneratorExit
```

These propagate unchanged. The `operator_interruption` taxonomy label records
their non-retry disposition for contract completeness; it does not authorize
the executor to construct a sanitized replacement exception or returned
outcome.

Controlled stop is owned by M7-A3c and is not part of this retry policy.

## 16. Sanitized observability

Future observability may emit only allowlisted aggregate or typed fields:

- outcome class;
- stable failure kind;
- allowlisted request kind;
- attempt ordinal and total attempt count;
- aggregate request/retry counts;
- selected sleep duration and aggregate delay counters;
- boolean budget and terminal indicators.

It MUST NOT emit:

- credentials, authorization values, cookies, or tokens;
- a hostname, URL, path, query, or CQL;
- raw response headers, including raw Retry-After;
- response bodies or parsed content;
- page/source/principal identifiers, titles, or filenames;
- local filesystem paths;
- raw exception class names, messages, tracebacks, or chained causes;
- full runtime hashes.

Typed policy errors and results MUST use body-free, secret-free `str` and
`repr`.

## 17. Deterministic contract acceptance matrix

The following cases are normative future test obligations. Each row assumes
sufficient request and delay budget unless the case states otherwise.

| Case | Expected outcome |
| --- | --- |
| HTTP 408, 429, 500, 502, 503, or 504 before final attempt | Matching `retryable_http_failure`; one bounded retry |
| Representative terminal 400, 405, 409, 410, 422, 501, or 505 | `terminal_http_failure/http_terminal`; zero retry sleep |
| Restriction 200, 401, 403, or 404 | `semantic_observation`; zero retry |
| Restriction 408, 429, 500, 502, 503, or 504 | Retryable operational failure; never an ACL observation |
| Retry ordinal 1, 2, 3 | Client backoff `1.0`, `2.0`, `4.0` |
| Four failed attempts | Four requests, three sleeps, then `attempts_exhausted` |
| M7-C crash after durable reservation before outbound I/O | One request-budget unit remains consumed; no actual attempt is claimed |
| M7-C resumed request budget | Durable reservations bound the run across process sessions; no refund occurs |
| Success on attempt 1 | One request, zero retry sleeps |
| Success on attempt 2 | Two requests, one selected sleep |
| Success on attempt 3 | Three requests, two selected sleeps |
| Success on attempt 4 | Four requests, three selected sleeps |
| Retry-After past HTTP-date | Parsed delay zero; backoff/rate wait applies |
| Retry-After future HTTP-date | Delay derived from injected UTC clock |
| Invalid Retry-After | Ignored; deterministic fallback applies |
| Negative Retry-After | Ignored; deterministic fallback applies |
| Duplicate or ambiguous Retry-After | Entire value ignored; no first-value selection |
| Retry-After exactly 120 seconds | Allowed subject to total-delay budget |
| Retry-After greater than 120 seconds | `retry_after_exceeds_policy`; no sleep/request |
| Accumulated plus next sleep exactly 300 seconds | Allowed |
| Accumulated plus next sleep greater than 300 seconds | `retry_delay_budget_exhausted`; no sleep/request |
| Rate-limit wait greater than retry component | One sleep equal to rate-limit wait |
| Request budget empty before initial attempt | `request_budget_exhausted`; zero requests/sleeps |
| Request budget empty before retry | `request_budget_exhausted`; no retry sleep or request |
| Malformed JSON after HTTP success | `payload_failure/malformed_json`; zero retry |
| Response exceeds byte limit | `payload_failure/response_too_large`; zero retry |
| Source identity mismatch | `payload_failure/identity_mismatch`; zero retry |
| State conflict | `state_failure/state_conflict`; zero retry |
| Raw-store failure | `state_failure/raw_store_failure`; zero retry |
| Checkpoint failure | `state_failure/checkpoint_failure`; zero retry |
| Durable reservation storage failure | `state_failure/checkpoint_failure`; zero retry |
| Inventory page budget overflow | `budget_exhausted/inventory_page_budget_exhausted`; zero retry |
| `KeyboardInterrupt` | Propagates unchanged; zero retry |
| `SystemExit` | Propagates unchanged; zero retry |
| `GeneratorExit` | Propagates unchanged; zero retry |
| Fake clock and fake sleeper replayed twice | Identical attempts, decisions, sleeps, and counters |

Future tests MUST additionally cover each typed retryable and terminal
transport failure kind, retry success/failure at every allowed attempt,
single-delay overflow caused by rate-limit wait, and exact request-budget
consumption.

## 18. M7-A2 independent-review gate

M7-A2 may be accepted only when an independent reviewer verifies:

- this specification contains the complete locked taxonomy and matrix;
- the YAML profile parses and exactly matches owner decision L;
- A1 status is synchronized without changing an A1 technical decision;
- no source, test, schema, or approved M5/M6 focused contract changed;
- no production behavior, network request, credential use, commit, or push
  occurred;
- no unresolved P0, P1, or P2 finding remains.

Until that verdict:

```text
M7-A2: COMPLETE AND APPROVED
M7-A3a/A3b/A3c: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

## 19. Dependencies and downstream blocking

M7-A2 depends on the owner-accepted M7-A1 scope and decisions. M7-A2 defines
request/retry semantics and materializes the numeric profile only.

M7-A3 owns checkpoint/run mechanics, overlapping-root deduplication,
generation-scoped restriction evidence, fingerprint canonicalization, and
controlled-stop acceptance. M7-B1 through M7-B3 own future structured HTTP
metadata, pure retry policy implementation, and the rate-limited retry
executor respectively.

M7-A3 and M7-B1 through M7-B3 are complete and approved. M7-C remains
separately gated; no production behavior is authorized by this specification or
profile alone.
