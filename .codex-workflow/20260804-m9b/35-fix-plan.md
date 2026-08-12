# M9-B Re-review Fix Plan 13

Address only `34-review-15.md`:

- Parse `cat-file --batch-check` lines strictly as exact OID/type/decimal-size
  records with required LF terminators; reject signs, CR, and missing LF.
- Validate document metadata field runtime types (exact int/bool/string) before
  semantic equality checks.
- Make `BuildGitCodeDocumentsRequest.__post_init__` deeply rerun config/profile
  validators so direct construction fails closed as well as execution.

Rerun scoped/regression validation and a fresh independent review.
