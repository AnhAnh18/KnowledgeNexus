# M10-C Fix Plan Input

Address every confirmed finding from the independent review in
`.codex-workflow/20260805-m10/45-m10c-independent-review.md` without
broadening M10-C:

1. Restrict the three generic report profile fields to safe identifier values
   that cannot be paths, URLs, secrets, or arbitrary report text, while keeping
   approved values such as `medium`, `provisional_until_benchmark`, and
   `1.2.0` valid.
2. Reject any non-exact `pathlib.Path` runtime value at the generic public
   `complete` boundary before invoking methods or inspecting the filesystem;
   preserve legacy behavior when `m10_quality is None`.
3. Make generic JSONL parsing reject blank lines as malformed input, retaining
   duplicate-key and non-finite-number rejection.

Add adversarial tests for path/URL profile values, wrong path-like objects with
side effects, and blank JSONL lines. Re-run focused M10-C tests, all M6G
completer/writer/publisher/one-page regression tests, architecture tests,
compileall, and diff-check. Use sanitized errors, preserve machine streams and
no-clobber cleanup, and do not change CLI, publisher, writer, network, or
roadmap/state until an independent re-review passes.
