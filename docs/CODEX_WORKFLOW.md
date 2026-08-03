# Codex Managed Workflow

This repository uses a milestone-first workflow for roadmap implementation.
The durable rules live in `AGENTS.md`; this document records the complete
sequence so a new Codex CLI session can recover the process without relying on
chat history.

## Required Sequence

For every implementation stage:

1. Confirm the current goal, roadmap state, and owner authorization. Inspect the
   working tree, isolate intended changes, and preserve unrelated existing
   changes; the managed pipeline additionally requires a clean tree before it
   starts a run.
2. Run an independent plan critic. The critic identifies missing requirements,
   risks, alternatives, acceptance criteria, and tests. Its response starts
   with `RECOMMENDED_IMPLEMENTATION_PROFILE: build` or `complex`.
3. Run a plan reviser. It writes the complete executable revised plan to the
   run artifact path before implementation begins. The original input plan is
   never edited.
4. Implement only the revised-plan scope. Record changed files, exact test
   commands, results, and residual risks.
5. Run focused validation, relevant regression suites, architecture checks,
   `python -m compileall -q src tests`, and `git diff --check` as applicable.
6. Start a fresh independent review session. The reviewer never edits files,
   reports concrete P0-P3 findings only, and must reach `VERDICT: PASS`.
7. Fix every confirmed finding in scope, rerun affected validation, and repeat
   the fresh review until PASS. Do not broaden the milestone.
8. Commit using the milestone prefix and push only after authorization,
   validation, and independent PASS. Never use a commit SHA as portable
   milestone state.
9. Update `.local_ai/IMPLEMENTATION_STATE.md` and `.local_ai/ROADMAP.md` with
   milestone status, gate/review outcome, and the next bounded stage.

## Pipeline

Prefer the managed script so it creates isolated run artifacts and enforces the
stage order:

```powershell
scripts/codex-pipeline.ps1 -PlanPath <plan.md>
```

The script creates `01-plan-review.md`, `02-plan-revised.md`, implementation
and review artifacts, fix-cycle reports, and a final handoff summary under the
run-specific `.codex-workflow/<run-id>/` directory. Do not edit the original
input plan or reuse a review session as an independent reviewer.

## Gates and State

- A plan review is not implementation authorization.
- Owner authorization is required whenever the roadmap or scope says so.
- A review PASS is required before commit/push; a test pass alone is not a
  review PASS.
- Scale measurements remain measurements unless the explicit scale gate passes.
- If a goal is blocked and the owner resumes it, perform a fresh blocked-state
  audit before continuing; do not silently claim the old goal was active.
- State docs describe milestones and gates, not repository-local SHAs.

## Safety

Do not read, print, commit, or transmit `.env`, `.local_ai/evidence/`,
`Tool_TRreport/`, raw/runtime data, credentials, or unsanitized Confluence
content. Preserve unrelated worktree changes and temporary artifacts.
