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

## Patch Discipline

- When creating patches, clearly say whether the patch is full/squashed or incremental.
- If a patch is incremental, state which previous patch it must be applied after.
- When a patch represents already-applied workspace changes, validate it with `git apply --reverse --check <patch>`.
