# M10-D/E Fix Plan Input

Address only the four findings in `56-m10de-independent-review.md`:

1. Make post-publication acceptance failure restore the exact pre-run
   `LATEST.txt` state where possible and remove only the newly owned final
   directory, without touching an existing snapshot or hiding the shared
   publisher's documented rename/LATEST failure semantics.
2. Make acceptance readback fail closed on validator mutation or validator
   side effects: validate defensive copies, compare them, and ensure the
   on-disk manifest/JSONL bytes are unchanged during each validation pass.
3. Sanitize non-integer `SystemExit` payloads in the CLI instead of calling
   `int()` on arbitrary values.
4. Include digest computation in the sanitized post-publication acceptance
   handling so filesystem/hash failures map to `acceptance`.

Add adversarial tests for pointer/final cleanup after report mutation,
stateful validator mutation and on-disk tampering, `SystemExit("secret")`,
and digest exceptions. Re-run focused M10-D/E, M10-A/B/C/M6G/M8/M9,
architecture, compileall, diff-check, and a fresh independent review before
roadmap/state, commit, or push.
