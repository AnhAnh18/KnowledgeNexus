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

- Is the commit small and reviewable?
- Is the commit message specific?
- Are local-only files such as bundles, raw/work/export data, and personal references excluded?
- If a patch file was created, does it clearly say whether it is full/squashed or incremental?
- If a patch file was created, was the matching review summary created or updated under `.local_ai/review/`?
- If the patch is incremental, does it state which previous patch it must be applied after?
- If the patch represents already-applied workspace changes, did `git apply --reverse --check <patch>` pass?
