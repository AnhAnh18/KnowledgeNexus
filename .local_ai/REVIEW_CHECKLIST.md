# Review Checklist

Before committing, check the following.

## Local Review Notes

- Store local review summaries and patch notes under `.local_ai/review/`.
- Use `.local_ai/review/<milestone-or-task-name>-review-summary.md` when a review summary is requested.
- Do not use `.local_ai/reviews/`.
- `.local_ai` is tracked so steering and review notes sync across machines. Commit
  it in its own commit, separate from production changes, so a code patch stays
  reviewable on its own.
- `.local_ai/evidence/` stays ignored: those packets are sanitized captures of a
  real internal Confluence and must not be committed.
- Never commit a filled request profile, packet, report, or any artifact holding
  a real host, token, space key, page ID, or title.

## Scope

- Did this task implement only what was requested?
- Did it create unrelated modules or future-step code?
- Did it avoid scaffolding the full canonical v7.5 tree unless requested?

## Architecture

- Does Foundation avoid importing indexing, retrieval, chat, or presentation?
- Does shared avoid business logic and business entities?
- Are concrete adapters kept in infrastructure?
- Are interfaces/ports added only when a use case needs them?

## Contracts

- Are `contracts/foundation/schemas` kept in git?
- Are generated/runtime files excluded?
- Are schemas loaded from `contracts/foundation`, not hardcoded elsewhere?
- Does any contract path refer to `contracts/foundation/contracts/` by mistake?

## Security

- No PAT/token/password values in committed files.
- `.env.local` ignored.
- `.env.example` has empty placeholders.
- Logs, reports, exports, and tests do not expose secrets.

## Tests

- Can imports pass?
- Do tests run?
- Are test fixtures small and non-secret?

## Git

- Is the commit message specific and tagged (`[<TASK>]`, `[SETUP]`, `[DOCS]`)?
- Is a setup or policy change tagged `[SETUP]` rather than with a task ID?
- Is the commit small enough to review? Beyond roughly 400 changed lines, or more
  than one independently reviewable concept, it should have been split into
  `[TASK-A]`, `[TASK-B]`, ...
- Does each split commit stand alone: builds, full suite passes, reviewable
  without the next one?
- Does each split commit carry its own tests, rather than separating production
  code from the tests that prove it?
- Are local-only files such as bundles, raw/work/export data, and personal references excluded?
- Was the review summary created or updated under `.local_ai/review/`?
- Does the review summary state the exact `BASE`..`TASK` range it covers?

## Patches (only when explicitly requested)

- Does the patch clearly say whether it is full/squashed or incremental?
- If incremental, does it state which previous patch it must be applied after?
- If it represents already-applied workspace changes, did `git apply --reverse --check <patch>` pass?
- Does it exclude `.local_ai` and unrelated working-tree changes?
