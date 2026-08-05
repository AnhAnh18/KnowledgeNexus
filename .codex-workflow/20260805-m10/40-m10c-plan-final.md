# M10-C Cross-Stream Projection and Generic Completion - Final

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Scope and compatibility

M10-B is complete and independently reviewed `PASS`; M8-AC remains
`pending_external_input`. Add only generic M10 completion behavior; do not
alter M6G models, CLI, legacy report bytes, writer/publisher behavior,
dataset-version generation, `LATEST.txt`, or external/run boundaries.

The additive signature is:

```text
FullSnapshotStagingCompleter.complete(
    *, staging_path, validator,
    one_page_quality=None,
    m10_quality=None,
)
```

When `m10_quality is None`, execute the existing legacy path unchanged. When
`m10_quality` is supplied, require exact `M10QualityReportInput`, require
`one_page_quality is None`, require a callable shared validator, and reject
all mode/type/forged/mutual-exclusion errors before filesystem inspection or
mutation.

## Generic M10 completion contract

1. Strictly read `manifest.json` and all eight JSONL streams with duplicate-key
   and non-finite-constant rejection. Validate untouched deep copies using the
   shared Foundation validator before any count/field access; detect validator
   mutation or exception and fail without creating `quality_report.md`.
   Require manifest schema validity, exact count keys and non-negative integer
   values, on-disk counts equal manifest counts, and
   `m10_quality.expected_counts` equal manifest counts. Require canonical
   source scopes with only sorted `confluence`/optional `git` keys and exact
   canonical equality with `m10_quality.source_scopes`. Permit non-empty
   `media_assets`, `symbols`, and `sync_state`; require initial
   `tombstones.jsonl` to be empty.

2. Validate the quality input before rendering: exact concrete fields,
   defensive nested copies, expected-count invariants, scalar metric values
   restricted to deterministic `bool|int|str` (no newlines, paths, URLs,
   exception text, raw content, principals, or secrets), fixed metric-section
   key sets, and boolean/string completion checks. Any mutation during
   validation/rendering fails closed. Rendering is pure and repeated runs
   produce identical UTF-8 bytes.

3. Render exactly these sections in this order, with fixed labels and sorted
   keys within each approved mapping: `Snapshot`, `Active Profiles`, `Record
   Counts`, `Jira Relation Quality`, `ACL Quality`, `Media Quality`, `Symbol
   Quality`, `Sync State`, `Tombstones`, `Completion Checks`, `Publication
   State`, and `Scope`. Include only typed profile/count/source-scope/metric/
   completion data and the required
   `PENDING_AT_REPORT_COMPLETION` markers; never include record text, raw
   content, secrets, exception text, or uncontrolled values.

4. Reuse existing report writer and cleanup/no-clobber semantics. All generic
   validation completes before report creation; a write or final-file-set
   failure removes only the owned report and leaves machine streams unchanged.
   No dataset version, final directory, or `LATEST.txt` is derived or written.

## Tests and acceptance

Add adversarial generic-mode tests for `None`, `object()`, wrong/forged
quality inputs, both modes, invalid validator, strict duplicate keys/NaN,
schema-invalid records, validator/quality mutation or exception, count and
source-scope drift, non-empty media/symbol/sync acceptance, non-empty
tombstones rejection, unsafe/pre-existing report paths, cleanup/no-clobber,
deterministic repeated report bytes, sanitization probes, and M6G golden
compatibility. Run focused M10-C plus the existing M6G exporter suite,
architecture tests, compileall, and diff-check before a fresh independent
review; only then update roadmap/state and commit/push.
