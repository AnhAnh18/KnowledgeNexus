# Managed Codex Workflow

When a task is run through `scripts/codex-pipeline.ps1`, follow the stage named
in the prompt and use only the run-artifact paths it provides. Do not edit the
original input plan.

- Plan critics identify missing requirements, risks, alternatives, acceptance
  criteria, and tests. Their final response must begin with
  `RECOMMENDED_IMPLEMENTATION_PROFILE: build` or `complex`.
- Plan revisers write a complete, actionable revised plan to the requested
  artifact path before implementation begins.
- Implementers make only the changes required by that revised plan, run the
  most relevant tests, and report the exact commands and results.
- Independent reviewers never edit files. Report concrete findings as `P0`,
  `P1`, `P2`, or `P3`; do not report style-only issues.
- Fixers address every confirmed finding in scope, add or adjust tests when
  needed, and do not broaden the task.
- Every public/application boundary requires an adversarial negative pass in
  addition to happy-path coverage: wrong runtime types must fail closed before
  field access or side effects, and typed result/status objects must reject
  impossible field combinations and cross-field counts.
- Reviewers must test malformed inputs such as `object()`, `None`, wrong enum
  values, missing required fields, forbidden extra fields, and impossible
  counters. Type annotations and dataclass construction are not runtime
  validation.

Never treat a review as independent if it shares a session with the agent that
implemented or fixed the code. A focused re-review uses the same `review`
profile as the initial review, but runs in a new independent CLI session. Do not read, print, commit, or transmit `.env`,
`.local_ai/evidence/`, `Tool_TRreport/`, raw/runtime data, credentials, or
unsanitized Confluence content.
