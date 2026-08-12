# M10-C Fix Plan - Final

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Scope

Fix only the three findings in `45-m10c-independent-review.md`:

1. Add a dedicated safe profile identifier check for
   `active_profile`, `profile_status`, and `chunker_version`. The accepted
   grammar is a non-empty ASCII identifier beginning with an alphanumeric and
   continuing only with alphanumerics, `.`, `_`, or `-`, bounded to 256
   characters. Reject paths, URLs, whitespace, control characters, and
   arbitrary report text before report rendering.
2. In generic `FullSnapshotStagingCompleter.complete`, reject any
   `staging_path` whose exact runtime type is not `Path` before any method
   call or filesystem inspection. Preserve the legacy branch byte-for-byte
   when `m10_quality is None`.
3. In `_read_strict_jsonl_records`, reject empty lines rather than silently
   skipping them. Keep duplicate-key and non-finite-number rejection.

## Tests

Extend the M10-C tests with unsafe Windows/Unix path and HTTP(S) profile
values, wrong path-like objects whose `exists()` would cause a side effect,
`object()`/`None` path values, and interior/trailing blank JSONL lines. Assert
sanitized errors, no report creation, no marker side effects, preserved
machine streams, and legacy output compatibility.

## Validation and handoff

Run focused M10-C plus existing completer regression, exact M6G
exporter/writer/publisher/one-page regression, architecture, `python -m
compileall -q src tests`, and `git diff --check`. Produce an implementation
report, then commission a fresh independent review. Only after final review
`PASS` may `.local_ai/ROADMAP.md` and `.local_ai/IMPLEMENTATION_STATE.md` be
updated and the bounded files/artifacts staged, committed, and pushed.

## Non-goals

No changes to the legacy one-page/M6G branch, schemas, writer, publisher,
CLI, connector, network, real-run gate, or M8-AC status.
