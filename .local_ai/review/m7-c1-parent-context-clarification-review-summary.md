# M7-C1 Parent Context Clarification Review Summary

## Decision

M7 occurrence `parent_page_id` is root-relative context, not stable
cross-occurrence metadata. It must be `None` for an empty ancestor path and
must equal the final ancestor ID otherwise. Compatibility compares the stable
metadata fields and exact suffix-compatible `(ancestor_page_id,
ancestor_title)` paths. The longest compatible path is canonical and supplies
the canonical parent.

This preserves existing M5 and M7-C1-A root-relative mapping while allowing a
selected root occurrence and its nested occurrence to deduplicate. Malformed
path/parent facts and stable metadata conflicts remain fail-closed.

## Scope

Only these authoritative documents changed:

- `contracts/foundation/CHECKPOINT_RESUME_SPEC.md`
- `contracts/foundation/CRAWL_RELIABILITY_SPEC.md`
- `contracts/foundation/decision_logs/M7_C_OWNER_DECISIONS.md`

No M5/M6 source, M7-C0/C1-A code, schema, persistence, network, or
orchestration behavior changed.

## Independent Review

Two independent plan critics selected the `build` profile and confirmed the
scope and required path/parent invariants. The first independent contract
review returned:

```text
VERDICT: PASS
```

An acceptance review found one P2 omission: the acceptance row did not state
that the canonical parent must equal the final ID of the selected longest
path. The acceptance row was corrected, and a fresh independent re-review
confirmed:

```text
VERDICT: PASS
```

## Validation

```text
git diff --check
PASS

python -m pytest -q tests/foundation/contracts --basetemp D:\Claude\KnowledgeNexus\.pytest-tmp-c1-parent-contract-rereview
31 passed
```

## Handoff

The clarification is ready to commit as a prerequisite contract decision for
the M7-C1-B pure run/occurrence implementation plan. No C1-B production code
has started.
