RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D1 Fix Plan 4 - Reviewed

## Objective

Address only the cyclic-container closeout finding in `15-review-4.md` while
preserving the existing tombstone schema checks, deterministic IDs, defensive
copy behavior, injected validator dependency, atomic failure contract, and
no-I/O/exporter boundary.

## Implementation

1. In `foundation/domain/models/tombstone_propagation.py`, harden the internal
   JSON-safe traversal used by `TombstoneProjectionResult` before any
   `deepcopy`. Track the identities of builtin `dict`, `list`, and `tuple`
   containers currently on the recursion path (`active_ids`), reject an ID that
   is encountered again as a cycle, and remove each ID in a `finally` block so
   shared but acyclic containers are not mistaken for cycles. Keep exact builtin
   type checks so subclasses and arbitrary objects fail closed without invoking
   user hooks.
2. Add a bounded-depth guard (or an equivalent `RecursionError` conversion) so
   pathological deeply nested builtin containers also become typed
   `TypeError`/`ValueError` failures rather than leaking `RecursionError`.
   Do not alter the accepted flat TombstoneRecord shape.
3. Keep the result boundary order: reject wrong outer record/container types,
   run cycle/depth-safe JSON validation and exact tombstone-shape validation,
   then perform the defensive copy inside its existing typed exception
   boundary. No partial copied record may be stored in a result.

## Scope

Modify only the JSON traversal/model implementation and focused model tests.
Do not change schemas, builders, use cases, exports, cascade rules, exporters,
stores, checkpoints, network code, clocks, or roadmap/state files.

## Required adversarial tests

- A schema-shaped result record containing a self-referential list in an extra
  field must raise `TypeError`/`ValueError`, not `RecursionError`, and must not
  invoke any copy hook.
- A self-referential dict and a mutually recursive dict/list pair must fail with
  the same typed boundary error.
- A deeply nested builtin container beyond the chosen depth bound must fail
  closed with `TypeError`/`ValueError`.
- A container graph that shares an acyclic child in two branches should be
  traversed without false cycle detection (it will still be rejected later if
  the TombstoneRecord schema shape is invalid).
- Preserve prior malformed-input coverage: `object()`, `None`, wrong runtime
  container/subclass types, missing required fields, forbidden extra fields,
  invalid enums/IDs/timestamps, nullable optionals, impossible metrics, forged
  models, validator mutation, and atomic zero-record failures.

## Verification and acceptance

Run the focused tombstone model/builder/use-case tests and all previously
required M9-D1, M9-A/B/C, M8-D/E, architecture, schema, and integration
regressions with a workspace-local pytest `--basetemp`. Also run
`python -m compileall -q src tests` and `git diff --check`. Acceptance requires
no recursion or arbitrary exception leakage, no I/O or validator dependency
changes, all tests passing, and a fresh independent closeout review in a new
CLI session before ledger, commit, or push.
