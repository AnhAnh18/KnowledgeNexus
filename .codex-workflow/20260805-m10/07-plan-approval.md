RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10 Plan Approval

APPROVED

The final plan closes the prior review blockers and is ready for implementation
under the complex profile. No plan-level blocker remains.

## Confirmed contract and compatibility

- Exact immutable wire models, field sets, runtime validation, status/category
  combinations, metric invariants, constants, profile/config derivation, and
  deterministic dataset-version rules are specified.
- M6G one-page models, CLI mappings, report bytes, deferred-stream behavior,
  and golden output remain unchanged. M10 uses only additive generic
  completion behavior and existing M3 writer/publisher/version APIs.
- Stream policy is explicit: media/symbol streams depend on policy and
  eligibility, diagnostic sync state is constrained and schema-valid, and
  initial tombstones are exactly empty.
- Adapter provenance, commit/path/line binding, Git ACL fallback, relation
  unresolved status, parent/ACL inheritance, and all-or-nothing projection are
  defined. Malformed runtime inputs fail before dependency or filesystem side
  effects.
- CLI categories map to closed exit codes, path/symlink/reparse/no-clobber
  rules are explicit, publication reads back all ten files, and `LATEST.txt`
  remains a separate pointer from the ten-file version directory.

## Acceptance gate

The listed focused M10 model/use-case, exporter, architecture, M8, M9, M3/M6G,
compileall, and diff-check commands provide the required validation sequence.
Implementation must preserve their explicit basetemps and report exact command
results. A fresh independent review must pass before roadmap/state updates,
staging, commit, or push. Real operator evidence remains aggregate-only and
`pending_external_input`; synthetic results cannot be promoted to a real POC
PASS.

Residual implementation risks (canonical digest serialization, exact source-ID
allowlists, and report rendering details) are covered by the locked model,
schema, determinism, compatibility, and adversarial tests in the plan and do
not block approval.
