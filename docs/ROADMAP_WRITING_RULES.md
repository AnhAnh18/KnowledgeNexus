# Roadmap Writing Rules

This is the repository-wide convention for planning and maintaining roadmaps.
It applies to new roadmaps and to new entries added to older roadmap files.
Historical IDs remain valid; new references must use the qualified form below.

## 1. Use qualified IDs

Every work item has a stable ID with an explicit namespace. Do not write a
bare `W5`, `I2`, or `R3` in a new plan when the parent/domain is known.

| ID pattern | Meaning | Example |
|------------|---------|---------|
| `M##` | Product/Foundation milestone | `M10` |
| `M##-W##` | Work package under a milestone | `M10-W5` |
| `IDX-I##` | Indexing stage | `IDX-I2` |
| `RET-R##` | Retrieval/search work item | `RET-R2` |
| `GATE-<domain>-##` | Acceptance gate | `GATE-RET-01` |
| `REV-<domain>-##` | Independent review | `REV-IDX-02` |

Use decimal children for implementation slices, for example `RET-R2.1` and
`RET-R2.2`. Do not reuse an ID for a different scope after it has been
published.

## 2. Separate planning levels

- Milestone: outcome and boundary, not a task list.
- Work package/stage: bounded implementation objective with dependencies.
- Task: one concept that can be implemented and reviewed independently.
- Gate: evidence required to move forward; a gate is not a feature.
- Review: independent assessment of a plan or implementation; it does not edit
  the implementation under review.

Do not mix milestone, work package, and task IDs in one column without naming
the level. Use separate columns such as `ID`, `Level`, `Owner`, and `Parent`.

## 3. Required fields for every active item

Each active item must state:

1. `Objective`: one observable outcome.
2. `Scope`: what changes.
3. `Out of scope`: what must not change.
4. `Dependencies`: qualified IDs and contract prerequisites.
5. `Acceptance`: tests, artifacts, and measurable gates.
6. `Owner`: role/team, not an assumed person.
7. `Status`: one value from the controlled vocabulary.
8. `Evidence`: link to tests, review, benchmark, or artifact.

If a field is not known, write `TBD` and add the decision needed to resolve it;
do not silently infer it during implementation.

## 4. Controlled status vocabulary

Use only:

```text
planned | ready | in_progress | blocked | review | done | deferred | cancelled
```

`blocked` requires a named blocker. `done` requires evidence. `deferred`
requires an activation condition. Do not use synonyms such as `todo`,
`later`, `current`, or `complete` in new roadmap sections.

## 5. Dependencies and sequencing

Write dependencies as a directed list of qualified IDs, for example:

```text
RET-R2 depends_on: M10-W5, IDX-I5, GATE-IDX-01
```

Distinguish `depends_on` (cannot start), `enables` (unlocks another item), and
`related_to` (informational only). A roadmap must not imply that a future item
is authorized merely because it is listed.

## 6. Acceptance and evidence

Acceptance criteria must be testable and include negative paths at every public
or application boundary. For typed results/statuses, test impossible field
combinations and counter mismatches, not only happy paths.

Record the exact command or benchmark label used as evidence. For quality work,
freeze the compared corpus/index and report quality, latency, cost, and safety
metrics. A claim of improvement without a baseline is not acceptance evidence.

## 7. Scope and change control

- One active item owns one coherent concept.
- Do not add implementation detail to later milestones until their dependency
  is activated and the scope is reviewed.
- A schema, identity, or lifecycle change must name migration, compatibility,
  re-index/re-ingest, and rollback implications.
- Deferred work stays deferred until its activation condition is met.
- Update the roadmap after a gate, scope decision, or status change; do not use
  it as a running implementation log.

## 8. Document structure

Every roadmap should begin with:

1. Purpose and boundary.
2. Naming legend and status vocabulary.
3. Current status table.
4. Dependency/order view.
5. Active work packages.
6. Gates and evidence links.
7. Deferred backlog.
8. Change log.

Keep normative field definitions in contracts/schemas. The roadmap links to
them rather than copying them, so the roadmap cannot drift from the source of
truth.

## 9. Naming files and headings

Use the leading qualified ID in new plan files and headings:

```text
RET-R2_CONTEXT_EXPANDED_RETRIEVAL.md
IDX-I0_COMPATIBILITY_REPORT.md
GATE-RET-01_CONTEXT_EXPANSION.md
```

Use a stable, concise title after the ID. Avoid dates, personal names, branch
names, and ambiguous labels in the canonical filename.

## 10. Historical compatibility

Do not rewrite completed historical records solely for style. When referring to
one, qualify it in new text: `M10-W5 (historically W5)`. New roadmap entries,
documents, and links must follow this convention.

