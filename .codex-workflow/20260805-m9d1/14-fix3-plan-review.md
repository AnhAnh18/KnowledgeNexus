RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D1 Fix Plan 3 - Reviewed

## Objective

Address only the two confirmed findings in `12-review-3.md`. Preserve all
earlier M9-D1 contracts: injected validator dependency, deterministic IDs,
schema-compatible nullable optionals, atomic failed results, pure/no-I/O
projection, fixed ordering, and no exporter wiring.

## Implementation steps

1. **Safe result-record validation and copying**

   In `foundation/domain/models/tombstone_propagation.py`, validate each input
   record's exact container type, JSON-safe value tree, exact tombstone key set,
   field types, enums, IDs, deterministic preimage, timestamp, versions, and
   nullable optional fields before invoking any copy operation. The JSON walker
   must accept only builtin JSON primitives/containers (reject subclasses and
   arbitrary objects), so a hostile value with `__deepcopy__` is rejected before
   its hook can run. After validation, perform the defensive `deepcopy` inside a
   `try/except Exception` boundary and convert any copy failure to a typed
   `TypeError`/`ValueError`; no arbitrary exception or partially copied record
   may escape. Revalidate the copied value if the implementation changes it or
   if that is needed to preserve the exact boundary contract.

2. **Exact forged-model field sets**

   Add a shared helper that checks `vars(instance)` against the exact dataclass
   field-name set before reading any model field. Apply it to
   `TombstoneTarget`, `TombstoneProjectionRequest`,
   `TombstoneProjectionMetrics`, and `TombstoneProjectionResult`, alongside
   the existing sentinel-safe reads and exact runtime-type checks. Missing or
   extra attributes, including an `extra` attribute injected with
   `object.__setattr__`, must raise only `TypeError`/`ValueError`. Request
   validation must continue to revalidate root and child targets, and
   `ProjectTombstones.execute` must map these forged-request failures to
   `invalid_request` with zero validator calls and no records/count leakage.

## Scope and files

Modify only the tombstone model, and focused tests (plus the use case only if
needed to preserve invalid-request classification). Do not restore implicit
`FoundationSchemaValidator` construction, add filesystem/network/clock calls,
change schemas or exporters, alter cascade policy, or touch unrelated M9/M8
modules. Keep existing additive exports and dependency injection intact.

## Required adversarial tests

- A record containing a custom object whose `__deepcopy__` increments a flag or
  raises `RuntimeError`: result construction must reject it before the hook is
  called and expose only `TypeError`/`ValueError`.
- A validator/result record using dict or primitive subclasses, custom keys, and
  malformed nested containers: reject before copying or side effects.
- For each tombstone model, forge an instance with `object.__new__`, omit a
  required field, add an `extra` field, or set a wrong runtime type; direct
  `__post_init__` calls must fail with typed errors and never `AttributeError`.
- Forge a root and child target inside a request, execute it through
  `ProjectTombstones`, and assert `INVALID_REQUEST`, `records == ()`,
  `count == 0`, one sanitized category, and zero calls to the injected
  validator. Cover `object()`, `None`, wrong enum values, missing fields,
  forbidden extras, malformed IDs, and impossible metrics at public/application
  boundaries as required by `AGENTS.md`.
- Retain prior tests for deterministic ID preimages, nullable optionals,
  validator mutation, atomic later-child failure, status/count invariants,
  dependency injection, purity guards, ordering, and unchanged exporters.

## Verification and acceptance

Run the focused tombstone tests, then the M9-D1/M9-A/B/C/M8-D/E regression,
architecture, schema-validator, and integration suites. Use workspace-local
`--basetemp` if host pytest temp permissions fail. Also run
`python -m compileall -q src tests` and `git diff --check`. Acceptance requires
all relevant tests pass, no side effects from hostile inputs or implicit schema
loading, and a fresh independent review in a new CLI session before ledger,
commit, or push actions.
