RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-B Fix3 Plan Approval

The fix3 plan is appropriately bounded and directly closes the P1 canonical
validator bypass from `33-m10b-fix2-review-final.md`.

## Approval Basis

- The shared concrete `FoundationSchemaValidator` remains authoritative for
  all seven non-tombstone streams; an injected/no-op observer cannot replace
  it. Exact concrete-type checks prevent fake or subclass canonical seams from
  bypassing required/additional-property schema enforcement.
- Construction failures and malformed validator inputs are required to be
  sanitized before any adapter call, while mutation detection, defensive
  copies, atomic failures, and prior provenance/ACL/media/relation/sync/result
  invariants remain in scope.
- The specified adversarial no-op-validator test exercises both seams with an
  extra-field record and verifies sanitized failure with zero projection/output.
- Scope is limited to M10-B source/tests/workflow artifacts; M6G/M9,
  exporters, CLI, roadmap/state, and real-run behavior remain protected.

## Required Verification

Before implementation is accepted, confirm the canonical validator is created
from the shared contract schemas, construction/type failures never leak raw
exceptions, and both default and explicit pure-composer paths reject missing
and extra fields before any downstream field access. Rerun the focused
M10-A/M10-B, bounded M9/M6G/architecture, compileall, diff-check, and fresh
independent-review gates listed in the plan.

VERDICT: PASS
