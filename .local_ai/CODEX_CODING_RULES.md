# Codex Coding Rules

## Scope

- Implement only the requested task.
- Do not implement future steps early.
- Do not scaffold the full canonical v7.5 tree as empty folders.
- Create folders only when code or tests need them.

## Architecture

- Use vertical Clean Architecture.
- Foundation must not import indexing, retrieval, chat, or presentation.
- Foundation may depend on shared utilities and `contracts/foundation` only.
- Application code depends on ports and domain rules, not concrete infrastructure.
- Infrastructure implements ports.
- Shared must not contain business entities.

## Foundation

- Connectors fetch source/raw data only.
- Connectors must not normalize, chunk, export, embed, or call Qdrant.
- Normalization, chunking, relation extraction, ACL extraction, media processing, symbols, and export belong to the Foundation pipeline.
- Foundation does not do embedding, Qdrant, retrieval, chat, or Gauss.

## Contracts

- `contracts/foundation/schemas` are authoritative.
- Export records must validate before writing.
- Indexing must validate snapshots before import.
- `ChunkRecord.text` must be embedded verbatim downstream.
- Do not silently drop in-scope content.
- Any skipped or omitted content must be scope-driven, policy-driven, or reported.

## Security

- Never commit PAT/token/password values.
- `.env.local` must be gitignored.
- `.env.example` contains empty placeholders only.
- Logs, reports, exports, and tests must not expose secrets.
- `.local_ai` is tracked, but `.local_ai/evidence/` is not: probe packets are
  sanitized captures of a real internal system.
- The repository is private and holds real internal identifiers (Confluence host,
  space key, root page ID, Jira project key, Git repo name) in `contracts/` and
  its git history. It must not be made public again without removing them.

## Testing

- Every task should include or update tests where practical.
- Keep commits small and reviewable.
- Do not add fake business logic just to satisfy tests.
- Prefer named constants for stable schema-facing literals instead of inline magic values.
- When two or more files share a stable schema-facing literal, move it to a common local constant instead of duplicating it.
- When builders copy mutable inputs such as lists or dicts into output records, add tests proving the output does not alias caller-owned objects.

## Plan Review

When given a task plan, review the whole plan and read the code it touches
*before* asking anything, then raise **every** question in one batch so the
author can answer once.

- Do not drip-feed questions across turns. Finish the analysis first: blocking
  issues, decisions the author must own, contradictions inside the plan,
  conflicts with a normative contract, and evidence gaps all go in the same
  message.
- Include what a decision costs, and give a recommendation. The author is
  choosing, not being surveyed.
- Batch the answers back the same way: state which decision governs each part
  before implementing.
- Only re-ask when the answers themselves conflict or an implementation fact
  emerges that no one could have known at plan time. Say plainly which it is.
- Prefer verifying against the repository over asking. Only ask what the code,
  contracts, and evidence cannot answer.

## Model Rotation Policy

- Implementation and review roles are model-agnostic.
- Claude and Codex may alternate roles between tasks.
- The implementation model must not perform the final independent review.
- The reviewer must inspect the repository and run tests independently.
- The first review pass must not modify the working tree.
- Accepted findings are fixed by the original implementer where practical.
- The same reviewer should perform the focused re-review.
- Critical filesystem, credential, network, migration, or data-loss changes
  require an Extra High independent review regardless of which model implements.

## Commit Authorization Gate

- **Default: review before commit.** Implementation changes remain unstaged or
  staged in the working tree until the independent review and focused re-review
  are complete and the repository owner explicitly authorizes committing them.
- Before creating the first task commit, the implementer must show the proposed
  commit stack (scope, code/test pairing, and order) and ask the repository owner
  for approval. A completed implementation step or green test run is not, by
  itself, permission to commit.
- When review can operate on the working tree, provide `git diff`,
  `git diff --cached`, changed-file scope, and exact test results. Do not create
  commits merely to manufacture review artifacts.
- If a reviewer requires `BASE`/`TASK` commit SHAs, ask the repository owner
  before creating candidate commits. Put authorized candidate commits on a
  local review branch, not directly on `main`, and do not push them unless push
  authorization is given separately.
- Candidate review commits are not automatically final history. After accepted
  findings are fixed and re-reviewed, the repository owner decides whether to
  keep the lettered stack, rebuild it, squash it, or commit the approved working
  tree in another form.
- Commit authorization and push authorization are separate. Permission to
  commit does not imply permission to push, and permission to implement does not
  imply either one.
- If a model commits without authorization, it must stop, report the exact
  commit SHAs and branch, avoid pushing or rewriting history, and ask the owner
  whether to keep, undo, or rebuild the commits.
- An explicit user instruction to commit, push, or prepare a commit-based review
  stack authorizes only that requested operation and scope.

## Commit Messages

- Prefix every commit with the work item it belongs to, in square brackets:
  `[<TAG>] <scope>: <lowercase summary>`.
- Use the task ID when the commit delivers that task: `[M5C1]`, `[M5B2]`, `[M4]`.
- Use `[SETUP]` for repository, tooling, ignore, or policy changes that are not
  part of any task's deliverable, even when they happen during a task.
- Use `[DOCS]` for documentation-only changes with no task deliverable.
- Do not tag a setup or policy change with a task ID: history should show what a
  task actually delivered.
- Keep the existing scope convention after the tag: `foundation:`, `docs:`,
  `chore:`.

## Commit Size and Splitting

Once commit creation is authorized, the commit is the review unit, so it must be
something a reviewer can hold in their head at once. M5C-1 landed as one commit
of 1631 lines: one undifferentiated block, which is what to avoid.

- The unit is **one cohesive piece of behaviour together with everything that
  proves it**: the transport and its tests, the adapter and its tests, the
  argument/validation layer and its tests. Related things stay together; a
  reviewer should be able to check one commit without holding the others open.
- Split a task into lettered commits when it delivers more than one such piece:
  `[M5C1-A]`, `[M5C1-B]`, `[M5C1-C]`.
- **Line count is a symptom, not the rule.** A large commit usually means several
  pieces got merged, so look for the seam — but do not split a genuinely single
  piece just to hit a number, and do not merge two pieces just because both are
  small.
- Split by layer or component, never by file type. Do not separate production
  code from the tests that prove it: a commit adding untested production code
  cannot be reviewed, and a commit adding tests for code that does not exist yet
  cannot pass. Each lettered commit carries its own tests.
- Every split commit must be green where it sits: it builds and the full suite
  passes at that commit, and it is reviewable without reading the *next* one. It
  may depend on the commits *before* it — that is the stack, not a defect. A red
  or half-finished intermediate commit is worse than one large commit.
- Prefer the seam the task already has. M5C-1's seams were the CLI
  argument/output-directory layer, the inventory execution and report writing,
  the verification and summary publication, and the runbook.
- If a task genuinely is one cohesive piece, keep it whole and say so in the
  review summary rather than splitting it artificially.
- Never split a security-relevant change so that an intermediate commit is
  exploitable.

### Review stack

When the repository owner authorizes commit-based review, deliver a split task
as an ordered review stack:

```text
BASE -> [TASK-A] -> [TASK-B] -> [TASK-C]
```

- Each lettered commit is a cohesive behaviour plus its own tests and must pass
  the full suite at that point. Later commits may depend on earlier commits;
  they are reviewed in order and are not required to be independently
  cherry-pickable onto `BASE`.
- Record `BASE`, every lettered commit SHA, and `REVIEW_HEAD` in the review
  summary. Review each commit/range directly from git; do not create patches by
  default.

### Squashing is opt-in

- **Default: keep accepted lettered commits in final history.** The layer/test
  boundaries stay visible to whoever reads the history later, which is most of
  the value of splitting in the first place.
- Squash them into one task commit only when explicitly requested by the
  repository owner or required by the target repository's merge policy.
- The implementer and reviewer must not assume squash by default.
- When a squash *is* requested, it must not change content. Verify the final
  squashed commit and the approved `REVIEW_HEAD` have identical trees with
  `git diff --exit-code <REVIEW_HEAD> <SQUASHED_HEAD>` (or equal tree IDs), and
  record `TREE_EQUIVALENCE=PASS` plus the final SHA in the review summary.
- Any content change made during or after the squash invalidates tree
  equivalence and requires focused re-review before the final commit is used.

### Behaviour and test pairing

Keep these changes with the tests that prove them in the same review commit:

| Behaviour/component | Tests that travel with it |
| --- | --- |
| Public API or domain model | contract, validation, invariants, and immutability tests |
| Port/interface | consumer-contract test or a minimal fake implementation used by its consumer |
| Infrastructure adapter/transport | request/response shape, error mapping, and offline boundary tests |
| CLI/API entrypoint | input validation, output/exit shape, sanitization, and credential-leak tests |
| Filesystem publisher | atomic publication, no-clobber, cleanup, and injected-failure tests |
| Serializer/exporter | schema validation, exact bytes/rows/counts/hashes, and malformed-output tests |
| Security boundary | negative regression tests proving the protected value or unsafe state cannot escape |

Do not create an API-only commit merely to reduce line count when the API has no
reviewable behaviour without its implementation. Keep the smallest meaningful
implementation and its proof together.

## Review Artifacts

- Do not create `.local_ai/review/*.patch` files by default. They cost tokens to
  produce and duplicate what git already stores; the commit itself is the review
  artifact. A reviewer reads `git show <sha>` or `git diff <base>..<head>`.
- Still write `.local_ai/review/<task>-review-summary.md`: it records decisions,
  probes, accepted findings, and verification, none of which git holds.
- Record the exact `BASE` and `TASK` commit range the review covers, so the
  reviewer does not have to guess.
- Create a patch only when explicitly asked, for example to move work to a
  machine without this git history.

## Patch Discipline

Applies only when a patch was explicitly requested.

- When creating patches, clearly say whether the patch is full/squashed or incremental.
- If a patch is incremental, state which previous patch it must be applied after.
- When a patch represents already-applied workspace changes, validate it with `git apply --reverse --check <patch>`.
- A patch file must exclude `.local_ai` and unrelated working-tree changes.

### Cross-repository transfer provenance

- A commit SHA identifies a tree in its own repository history. Treat a SHA
  from a separate implementation or review repository as source-review
  provenance only; never require an independent target repository to check out
  that foreign SHA.
- After applying approved patches to an independent repository, create a local
  transfer commit before an operator acceptance run. Record that local commit
  as the execution base.
- Record source-review provenance and local execution provenance separately.
  Demonstrate that the local production tree is equivalent to the approved
  patch set; do not infer equivalence from similar commit messages or filenames.
- A patch transfer does not preserve commit identity when the parent history
  differs. Do not claim that `git apply`, `git am`, or a reconstructed commit
  retained the source SHA unless the complete commit object and parent history
  are actually identical.
