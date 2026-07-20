# M6A Controlled Live Run - Sanitized Evidence Summary

## Evidence Boundary

This file registers operator-reported controlled-live evidence from the
Confluence-connected primary machine. The Codex checkout did not perform the
request and does not contain the raw production artifact.

The target repository is independent from this repository, so its commit SHA is
different from the reviewed source SHA. The source implementation was reviewed
through `5542311`; the operator ran the transferred M6A code at target production
head `e2823f9ca492becb17d6b2352aeada6bdf85d3ae`.

No hostname, page ID, title, raw path, raw hash, raw body, credential, principal,
or other production content is recorded here.

## Preflight

- The first target full-suite run exposed a missing `rfc3339-validator` runtime
  dependency: 9 date-time format tests failed because `jsonschema.FormatChecker`
  had no RFC 3339 checker available.
- The operator confirmed that this environment issue was corrected from the
  repository `requirements.txt`. It was not an M6A production-code failure.
- The exact post-install test count was not copied into this evidence record.

## Controlled Live Result

- Exit code: `0`.
- `method_get=true`.
- `status_success=true`.
- `json_valid=true`.
- `identity_match=true`.
- `artifact_written=true`.
- `hash_verified=true`.
- `temporary_cleanup=true`.
- Artifact existence check: PASS.
- Task-owned temporary-file absence check: PASS.
- Credential/deployment/page-identity leak scan: PASS.
- Live worktree `git status --short`: clean.

## Acceptance

The M6A controlled live behavior passed at the recorded target production head.
The raw artifact remains outside Git for M6B input. The repository owner accepted
this sanitized documentation/state closeout. `M6A_FINAL_HEAD` is the closeout
commit containing this state; M6B may begin after that commit is created.
