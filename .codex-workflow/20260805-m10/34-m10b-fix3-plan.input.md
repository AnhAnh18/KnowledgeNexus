# M10-B Canonical Validator Bypass Fix

Address only the P1 finding in
`.codex-workflow/20260805-m10/33-m10b-fix2-review-final.md`.

- Make the canonical validator a concrete shared `FoundationSchemaValidator`
  boundary, never an arbitrary caller-supplied protocol implementation. If a
  canonical validator argument remains for pure-composer testing, require the
  exact shared concrete type and reject subclasses/no-op fakes before record
  access; the application constructor must sanitize any construction/type
  failure before adapter calls.
- Keep the injected validator as an additional isolated observer, but a no-op
  injected validator must still be unable to bypass canonical schema
  validation. Preserve mutation detection, sanitized exceptions, defensive
  copies, and atomic failure behavior.
- Update only M10-B source/tests/workflow artifacts. Add an adversarial test
  passing no-op validators for both seams with an extra-field record and assert
  sanitized failure/zero projection. Preserve all prior M10-B invariants and
  rerun focused/bounded tests, compileall, diff-check, and a fresh independent
  review. Do not touch roadmap/state/exporter/CLI.
