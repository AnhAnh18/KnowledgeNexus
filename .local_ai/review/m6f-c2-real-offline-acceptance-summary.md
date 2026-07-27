# M6F-C2 Real Offline Acceptance Summary

## Verdict

M6F-C2 real captured-sidecar offline acceptance is complete and independently
approved. No rerun is required.

## Provenance

- Approved source-review head: `74fdbf1`.
- Source production merge head: `c12dcc2`.
- Main-machine transfer head: `7feae06`.
- Main-machine execution head: `2034ea4`.
- The execution head was committed and frozen before the run.
- The operator transcript proves the execution head and a clean tracked
  worktree immediately before the run.
- The tracked worktree was unchanged by the run.
- All nine scoped production, contract, and test blobs at the execution head
  exactly match the approved source-review blobs.
- Untracked operator artifacts were outside the tracked-worktree cleanliness
  gate and were not modified by the acceptance path.

These SHAs belong to independent repository histories and are provenance for
their respective repositories. Equality is established by the scoped blob
comparison, not by requiring equal commit identities.

## Sanitized Acceptance Gates

- Exit code zero: pass.
- Captured M6B evidence accepted: pass.
- Exact M6A ancestry binding: pass.
- ACLRecord and final chunk schema validation: pass.
- Canonical document unchanged: pass.
- Relations unchanged: pass.
- Only chunk ACL tags changed: pass.
- ACL propagation: pass.
- Deterministic repeat: pass.
- Raw page unchanged: pass.
- External sidecar unchanged: pass.
- Tokenizer profile and asset integrity: pass.
- Network used: false.
- Output files created: false.
- Focused and tokenizer-backed tests: pass.
- Evidence leak scan: pass.

## Safety Boundary

This summary intentionally excludes page and principal identifiers, filesystem
paths, crawler identity, internal URLs, raw content, exact timestamps, detailed
observation counts, tokenizer asset size/hash, and full artifact hashes. The
real raw page and captured sidecar remain external and uncommitted.

M6F-C2 is complete and approved. M6F-D documentation closeout is next; M6G
persistence/export integration has not started.
