# M7-C1-B Run Occurrence Review Summary

## Scope

M7-C1-B adds only pure, immutable crawl-run and inventory-occurrence domain
facts plus deterministic compatibility projection. It preserves existing M5
inventory and C1-A window behavior. It does not add persistence, locks,
transport, orchestration, retries, CLI behavior, raw generation, or network
I/O.

## Decisions Recorded

- Direct selected roots remain `InventoryRootCommit` facts. Descendant windows
  never encode roots through sentinel cursor or item-ordinal values.
- The resolver accepts explicit `InventoryRootCommit | InventoryOccurrence`
  facts. This resolves the C1-B boundary conflict: a direct nested root can
  deduplicate with the same page observed beneath an outer root without
  weakening descendants-only provenance.
- A descendant occurrence must have a non-empty root-relative ancestry whose
  first ID is its selected root. A selected root may still occur as a
  descendant under a different outer selected root.
- `parent_page_id` remains occurrence context under OD-C14. The longest
  suffix-compatible pair path supplies the canonical parent and scope path.
- Equality-sensitive C1-B boundaries accept only exact C1-B fact and
  primitive types. Nested metadata, roots, run IDs, windows, and transitions
  are reconstructed and revalidated so frozen-object tampering, subclasses,
  custom equality, and malformed iterators fail closed with sanitized errors.

## Independent Review

The review loop found and corrected the following concrete durability issues:

- nested selected roots were initially rejected as outer-root descendants;
- transition sequence and tampered transition-ordinal validation were
  incomplete;
- descendants accepted empty ancestry even though direct roots are distinct
  facts, and window commits did not revalidate a tampered occurrence page ID;
- root metadata and all fact boundaries accepted subclass/custom-equality
  values, and a tampered window iterator could expose a raw exception;
- C1-B primitive fields accepted custom string equality values.

The revised boundary plan is recorded at
`.codex-workflow/20260801-130605-7d1ca2a5/03-plan-revised-boundary.md`.
It was independently criticized before the boundary implementation resumed.

The final fresh independent reviews returned:

```text
Technical: VERDICT: PASS
Governance: VERDICT: PASS
```

## Validation

```text
python -m compileall -q src/knowledgenexus/foundation/domain/models/confluence_crawl_run.py src/knowledgenexus/foundation/domain/models/confluence_inventory_occurrence.py src/knowledgenexus/foundation/domain/rules/confluence_inventory_occurrence_resolver.py
PASS

python -m pytest -q tests/foundation/domain/models/test_confluence_crawl_run.py tests/foundation/domain/models/test_confluence_inventory_occurrence.py tests/foundation/domain/rules/test_confluence_inventory_occurrence_resolver.py --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c1b-primitives-focused
28 passed

python -m pytest -q tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/confluence --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c1b-primitives-app-infra
316 passed

python -m pytest -q tests/foundation/domain/models tests/foundation/domain/rules tests/foundation/application/use_cases --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c1b-primitives-domain
1154 passed

git diff --check
PASS
```

The exact temporary directories above were removed after validation.

## Closure Boundary

M7-C1-B is implemented, validated, and independently reviewed. Durable store,
resume registry, locking, request reservation, and coordinator behavior remain
separately scoped M7 stages.
