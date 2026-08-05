RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D1 Fix Plan 4 - Reviewed and Amended

## Objective

Address both confirmed closeout findings in the updated `16-fix4-plan.input.md`:
cyclic builtin-container traversal and arbitrary defensive-copy exceptions.
Preserve the existing schema-shape validation, deterministic IDs, nullable
optionals, injected validator dependency, atomic result contract, purity, and
no-exporter-wiring scope.

## Implementation

1. **Cycle-safe JSON validation before copying**

   In `foundation/domain/models/tombstone_propagation.py`, harden the internal
   JSON-safe traversal used by `TombstoneProjectionResult` before any
   `deepcopy`. Track identities of builtin `dict`, `list`, and `tuple`
   containers currently on the recursion path (`active_ids`), reject a repeated
   active identity as a cycle, and remove identities in a `finally` block so
   shared but acyclic children are not false positives. Keep exact builtin type
   checks so subclasses and arbitrary objects fail without invoking user hooks.
   Add a bounded-depth guard or equivalent `RecursionError` conversion so
   pathological nesting also becomes typed `TypeError`/`ValueError`.

2. **Contain every unexpected defensive-copy exception**

   Preserve the boundary order: reject wrong outer types, run cycle/depth-safe
   JSON and exact tombstone-shape validation on the original record, then copy.
   Wrap `copy.deepcopy` in `try/except Exception` (not only `TypeError` and
   `ValueError`) and convert any `RuntimeError` or other ordinary exception to a
   sanitized typed `TypeError`/`ValueError`. Do not catch process-control
   `BaseException` subclasses. No partially copied record or original exception
   detail may escape, and no copy hook may run for values rejected by the
   pre-copy validator.

## Scope

Modify only the JSON traversal/result model implementation and focused tests.
Do not change schemas, builders, use cases, exports, cascade policy, exporters,
stores, checkpoints, network code, clocks, or roadmap/state files.

## Required adversarial tests

- Self-referential list, self-referential dict, and mutually recursive
  dict/list values in a result record must fail with `TypeError`/`ValueError`,
  never `RecursionError`; verify no custom `__deepcopy__` hook is invoked.
- A deeply nested builtin container beyond the chosen depth bound must fail
  closed with a typed error; an acyclic shared child must not be identified as a
  cycle (it may still fail the flat TombstoneRecord shape afterward).
- Monkeypatch the module's `copy.deepcopy` to raise `RuntimeError` after
  pre-copy validation; result construction must convert it to `TypeError` or
  `ValueError` with no arbitrary exception leakage or partial record.
- Retain the custom-value `__deepcopy__` side-effect test, proving malformed
  values are rejected before copy, plus all prior malformed boundary cases:
  `object()`, `None`, wrong container/subclass types, missing/extra fields,
  invalid enums/IDs/timestamps, nullable optionals, impossible metrics, forged
  models, validator mutation, and atomic zero-record failures.

## Verification and acceptance

Run focused tombstone model/builder/use-case tests and all existing M9-D1,
M9-A/B/C, M8-D/E, architecture, schema, and integration regressions with a
workspace-local pytest `--basetemp`. Also run `python -m compileall -q src
tests` and `git diff --check`. Acceptance requires typed fail-closed behavior
for cycles and copy failures, no I/O or dependency changes, all tests passing,
and a fresh independent closeout review in a new CLI session before ledger,
commit, or push.
