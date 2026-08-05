# M9-B Re-review Fix Plan 3

Address only `13-review-4.md`:

- Revalidate every observation path with `_safe_path` at snapshot and plan
  boundaries, including forged instances.
- Require each `authority_observations` entry to be field-identical to the
  corresponding included observation, preventing provenance substitution.
- Cross-check plan raw/normalized byte counters against all observations.
- Require direct plan chunk `token_count` to be an exact integer in the active
  bounded range (1..1000); application validation remains responsible for the
  tokenizer-derived exact count.

Add direct adversarial tests for each forged case. Rerun focused/regression
suites, compileall, diff-check, and another independent review. Ledger updates
remain blocked until `VERDICT: PASS`.
