# M6F-C1 Review and Live-Capture Summary

## Review range

```text
M6F_B_FINAL_HEAD=ee83d9f
M6F_C1_A=855789d
M6F_C1_REVIEW_HEAD=bf6b79a
TASK_STATE=complete and approved
IMPLEMENTER=Codex
INDEPENDENT_REVIEWER=Claude
```

The source-review SHAs above identify the reviewed source-repository tree only.
They are provenance, not checkout requirements for an independent repository
that received the code through approved patches.

## Controlled live closure

- Exactly one separately authorized controlled live read-only capture ran.
- Exit code was zero, the approved seven-line stdout contract passed, stderr
  was empty, and the bounded sidecar envelope gates passed.
- The external sidecar remains external, uncommitted, and unmodified.
- The live execution changed no tracked file and no C2 work started.
- A pre-existing tracked documentation-only contract modification was
  independently inspected. It changed no capture behavior, serialization,
  publication, evidence acceptance, or C2 semantics.
- The dirty-worktree condition is accepted as P3/non-blocking, with no semantic
  impact and no recapture required.
- Final live verdict: **APPROVE**. Open findings: P0=0, P1=0, P2=0.

No credential, internal URL, filesystem path, sidecar name, source identifier,
principal, content, exact artifact size, or full hash is retained here.

## Delivered behavior

- Extends the existing M6B operator command with the opt-in
  `--restriction-observations-sidecar-out` argument.
- Leaves default M6B execution and its six success lines unchanged.
- In capture mode, validates an absolute external absent target before reading
  credentials, constructing the transport, or making a network request.
- Derives the repository root from the resolved CLI module location and
  requires the two locked source/contract marker files.
- Rejects repository-internal targets, missing/non-directory parents,
  symlink/reparse parents, existing/dangling-link targets, and unsupported
  Windows path forms.
- Serializes the exact returned
  `PageObservationCollectionResult.restriction_observations` into the locked
  deterministic JSON envelope without sorting source arrays.
- Enforces the shared 16 MiB cap over exact final UTF-8 bytes including LF.
- Publishes through an exclusively created same-parent temporary plus atomic
  no-clobber hard link; it never falls back to overwrite or a visible partial
  final file.
- Appends only `restriction_sidecar_written=true` after successful publication.
- Maps capture failures to the sanitized CLI categories and exit codes:
  `sidecar_target`/11, `sidecar_serialization`/12, and
  `sidecar_publication`/13.

## Contract synchronization

`ACL_MATERIALIZATION_SPEC.md` now locks the shared producer/loader byte cap and
keeps the C1 operator categories separate from the ACL materialization domain
taxonomy. The 16 MiB value is an independent artifact safety limit, not a claim
that every otherwise-valid M6B result must fit.

## Failure and ownership semantics

- Invalid target: zero credential reads, transport construction, and network.
- Serialization/publication failure: no success output and no final sidecar
  created by this command.
- A raced foreign target is never overwritten.
- Raw restriction and attachment artifacts already written by M6B are
  preserved; collection is not rerun after publication failure.
- Prepared targets and exceptions do not render filesystem paths.
- The sidecar may contain the normalized source IDs/principals needed by C2,
  but stdout, stderr, and this durable summary contain none of those values.

## Verification

```text
Focused C1:
56 passed, 1 skipped

Relevant M6B + M6F regression:
364 passed, 1 skipped

Full offline matrix with exact pinned local BGE-M3 tokenizer bundle:
1487 passed, 1 skipped

git diff --check:
PASS
```

The single skip is the POSIX permission-mode assertion on Windows. The Windows
publication, no-clobber, concurrency, symlink/reparse, cleanup, path, and CLI
security tests ran.

No test performed a live Confluence request. The full matrix ran with
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

Independent review reproduced 56 focused tests and 1,436 broad non-asset
offline tests with the same single Windows-expected skip. Verdict: **APPROVE**,
with no P0, P1, or P2 finding.

## Accepted P3 observations

- The controlled-live runbook must require an external filesystem with
  hard-link support (NTFS or a suitable POSIX filesystem). exFAT/FAT or another
  unsupported filesystem fails closed as `sidecar_publication`.
- Directory fsync is deliberately best-effort and a no-op on Windows; file
  flush/fsync and atomic hard-link publication still run.
- Passing non-bytes directly to the defensive publisher maps to
  `sidecar_serialization`. Production composition always passes the bytes
  returned by the serializer, so this category choice is accepted.

## Boundary confirmation

- No M6B application/domain observation semantics changed.
- No sidecar loader or M6A ancestry binding exists.
- No ACL materialization is invoked by C1.
- No persistence, snapshot export, M6F-C2, M6F-D, or M6G work exists.
- No JSON Schema changed.
- No credential value, source observation, sidecar path, or raw content is
  printed.

## Approved review stack

```text
ee83d9f
  -> 855789d [M6F-C1-A] foundation: add bounded no-clobber restriction sidecar
  -> bf6b79a [M6F-C1-B] foundation: add opt-in M6B sidecar capture
```

The intermediate C1-A tree independently passed the full offline matrix:
1,473 passed and one Windows-expected skip. The accepted lettered commits remain
the default final history; no squash was requested.
