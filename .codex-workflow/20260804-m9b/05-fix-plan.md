# M9-B Review Fix Plan

Address every finding from `04-review-1.md` without expanding M9-B:

1. Enforce `max_in_memory_bytes` using deterministic UTF-8 byte accounting for
   raw/normalized observations, canonical records, chunk texts/records, and
   authority copies before constructing a successful plan; reject atomically
   with `budget_exceeded`.
2. Require tokenizer spans to satisfy exact `0 <= start < end <= len(text)` and
   strict non-overlap/order; add forged negative/zero-length/oversized span
   tests.
3. Revalidate repository observations at the application boundary: recompute
   raw size, decode/normalize/hash normalized text, reject unsafe controls,
   verify authority classification from the immutable path, and reject
   mismatched identities/counters before document construction.
4. Strengthen `CodeDocumentPlan` and application validation for exact document
   and chunk projections, document/path identity, ACL/source/profile/version,
   line range and part contiguity/part-total consistency, content hash and
   tokenizer-count equality, and metrics cross-checks.
5. Make the Git runner private-contract safe: allowlist only the exact
   `rev-parse`, `symbolic-ref`, `ls-tree`, `cat-file --batch-check`, and
   `cat-file --batch` argv forms; reject remote/mutating/user-option commands.
   Enforce caps before returning injected results and use bounded streaming
   subprocess reads instead of unbounded `subprocess.run` capture.
6. Validate `GitSourceConfig.clone_root` existence, directory identity, final
   name, and all ancestor reparse components in the model (reader retains the
   pre-I/O check).
7. Validate tree object IDs as lowercase hexadecimal and reject C0/C1 path
   controls, with adversarial tests.
8. Validate constructor dependencies in `BuildGitCodeDocuments.__init__` and
   preserve the no-I/O-before-validation guarantee.

Run the focused M9-B suite plus M9-A/M8-D/E regressions, architecture,
compileall, and diff-check. Re-run an independent review in a new CLI session;
do not update ledgers or commit until `VERDICT: PASS`.
