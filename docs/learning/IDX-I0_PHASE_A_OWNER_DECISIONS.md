# IDX-I0 Phase A Owner Decisions

Status: **done**

This document records the owner dispositions for Phase A. It is documentation
only and does not authorize Phase B or any production implementation.

## Decisions

### A1 - Commit tags

Use the qualified `IDX-*` tags (`IDX-C1`, `IDX-B1`, `IDX-I1`, and so on). The
legacy `[HANDOFF-*]` candidate strings are removed from the handoff plan.

### A2 - Repository ownership and synchronization

`D:\Claude\KnowledgeNexus` owns `contracts/foundation/` and the Foundation
producer. `config/` belongs to the read-only Indexing bundle. Synchronization is
one-way from the outer repository to the bundle and is verified with parsed-JSON
equality or SHA-256 after LF normalization. No runtime code is copied in the
opposite direction.

### A3 - Pre-D12 snapshots

Snapshots published before D12 with ten files and no digest-set are re-exported
offline from retained raw/work state. No compatibility flag and no recrawl are
allowed. The re-export receives a new `dataset_version` and its delta base chain
is rebound to that version.

### A4 - D12 member inventory

The digest-set is the source of truth for snapshot membership. I1 verifies that
the actual file set equals the digest-set entries plus the digest-set itself.
Allowed names are keyed by `schema_version`; the resolver must not hard-code a
numeric file count.
Phase A records the membership disposition only. It does not invent a
`manifest.dataset_name` field or authorize IDX-C1 to implement a dataset
identity form that has not been separately approved.

### A5 - RET-R2 supersession

RET-R2 supersedes historical M11-A through M11-D. `.local_ai/ROADMAP.md`
section 12.1 records that status and links to the RET-R2 implementation and
context documents. RET-R2 remains parked until its stated retrieval gates are
met.

### A6 - Indexing implementation ownership

I1-I5 are developed in the outer repository. Importing the Indexing base from
the bundle is owned by IDX-I2-A after the post-W5-D head is frozen. The
`prior-art/indexing-importer-draft` branch is not merged.

### A7 - Digest-set specification

The normative docs-only specification is
`docs/learning/IDX-D12_DIGEST_SET_SPECIFICATION.md`. It defines the exact file,
encoding, canonical member order, fields, version binding, self-hash exclusion,
staging timing, schema-version extension rule, and control-plane digests.

### A8 - IDX-I1 dependency split

IDX-I1 has two gates:

- **Implementation gate:** the library-only resolver may start after A4 and A7
  are recorded. It does not depend on IDX-C1 implementation or IDX-B1 delivery.
- **Acceptance gate:** resolver acceptance still depends on IDX-C1, IDX-B1,
  and the frozen post-W5-D head.

This split does not authorize Phase B. A separate owner GO is required.

## Evidence

- Handoff candidate tags: `docs/learning/FOUNDATION_INDEXING_SNAPSHOT_HANDOFF_PLAN.md`
- M11 supersession: `.local_ai/ROADMAP.md` section 12.1
- Digest-set contract: `docs/learning/IDX-D12_DIGEST_SET_SPECIFICATION.md`
- I1 dependency record: `docs/learning/IDX-I0_INDEXING_SNAPSHOT_CONSUMPTION_GOAL.md`
