RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-B Fix2 Plan Review

The fix2 plan directly addresses the four findings in
`27-m10b-review-final.md`: canonical schema validation cannot be bypassed by a
no-op validator, ordinary composition exceptions are sanitized, Git chunk
paths use the approved grammar, unresolved `unknown` placeholders are
rejected, and source ownership is checked before merging.

## Required Clarifications

- Define the complete forbidden-placeholder/target grammar for every
  unresolved relation status. Rejecting the literal `unknown` is necessary but
  insufficient if arbitrary fabricated values such as `none`, `null`, or
  `unresolved` can still cross the boundary; retain schema-valid explicit Jira
  markers and require the approved external-target identity for non-Jira
  statuses.
- Explicitly include `sync_state` ownership in both handoffs: Confluence may
  provide page/attachment sync rows and Git may provide file/repository sync
  rows. The current ownership sentence lists neither sync rows, leaving valid
  sync handoffs ambiguous and risking accidental rejection or cross-source
  acceptance.
- Specify validation order and mutation detection: canonical validation must
  run on an untouched deep copy before any record field access; the injected
  validator must receive a separate copy, and any mutation or exception must be
  detected and converted to a sanitized atomic `PROJECTION` failure.
- Define behavior if canonical schema loading/validation itself raises or the
  default fallback cannot be constructed. This must fail closed without
  adapter calls, partial projection, filesystem writes, or leaked exception
  text.

## Acceptance Coverage

The listed tests are appropriate, but add parametrized checks for Confluence
and Git `sync_state` ownership, all unresolved relation statuses and forbidden
placeholder variants, canonical-validator failure/mutation, and a missing
required field that would otherwise trigger `KeyError`. Preserve zero-call
invalid-request behavior, atomic empty results, exact result/metrics checks,
M6G/M9 schemas and architecture regressions, compileall, diff-check, and a
fresh independent review.

VERDICT: CHANGES_REQUIRED
