# M10-D/E Fix Plan - Final

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

Implement exactly the four fixes listed in `57-m10de-fix-plan.input.md`:

- Snapshot prior `LATEST.txt` bytes/existence and the new final path before
  publication. If post-publication acceptance fails, restore the pointer
  atomically (or remove the newly advertised pointer when none existed) and
  remove only the newly created final directory; preserve prior snapshots.
- During acceptance, validate deep-copied records and reject validator
  mutation. Capture manifest/JSONL bytes before validation and reject any
  validator-induced on-disk mutation.
- Handle `SystemExit` only with an actual integer code; all other payloads
  return sanitized unexpected JSON and exit code 1.
- Compute the snapshot digest inside the acceptance try/except and map all
  failures to `M10SnapshotExportFailure("acceptance")`.

Add focused adversarial tests, rerun the bounded regression matrix, then
commission a fresh independent review. No roadmap/state changes before PASS.
