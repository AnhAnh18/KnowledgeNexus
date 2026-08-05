RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-C Plan Approval

The final approved plan closes the outstanding review requirements.

- Generic mode requires the exact concrete shared `FoundationSchemaValidator`
  before filesystem inspection; protocol fakes/subclasses are rejected and
  construction, parsing, validation, and rendering failures are sanitized with
  no report or stream side effects.
- Manifest source scopes have an exact deterministic schema and canonical
  equality with typed quality input. All eight count keys, exact stream counts,
  empty initial tombstones, and permitted non-empty media/symbol/sync streams
  are explicit.
- Quality metric sections and completion checks have fixed key sets, integer/
  boolean constraints, cross-count consistency, and controlled scalar values;
  report output is limited to the twelve fixed sections with deterministic
  ordering and publication markers.
- Legacy `one_page_quality` behavior remains byte-identical and mutually
  exclusive with generic mode. Validation precedes report creation, existing
  no-clobber/cleanup semantics are preserved, machine streams remain unchanged,
  and no dataset version or `LATEST.txt` is written.
- Adversarial, M6G golden, architecture, compileall, diff-check, and fresh
  independent-review gates are included, with no scope expansion.

VERDICT: PASS
