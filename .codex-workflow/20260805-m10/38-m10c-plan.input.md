# M10-C Cross-Stream Projection and Generic Completion

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

M10-B is complete and independently reviewed `PASS`; M8-AC remains
`pending_external_input` and is not required for this synthetic completion
stage. Implement only the approved M10-C boundary:

1. Extend `FullSnapshotStagingCompleter.complete` additively with a generic
   `m10_quality` keyword accepting `M10QualityReportInput`. Preserve the exact
   old `one_page_quality=None|OnePageExportQualityReportInput` behavior,
   report bytes, file-set checks, no-clobber semantics, cleanup, and golden
   output. Reject passing both quality modes or wrong runtime objects before
   filesystem mutation.

2. In generic M10 mode, validate the manifest and every JSONL record against
   the shared Foundation schemas on strict duplicate-key/non-finite-safe
   readback. Require exact eight count keys, counts equal on-disk records and
   `m10_quality.expected_counts`, deterministic source scopes, and the initial
   `tombstones.jsonl` file to be empty. Unlike M6G deferred mode, permit the
   M10 media, symbols, and sync streams to be non-empty. Detect validator
   mutation/exception and quality-input mutation; fail atomically without
   leaving `quality_report.md`.

3. Render a deterministic generic M10 quality report from only typed profile,
   count, source-scope, relation/ACL/media/symbol/sync/tombstone metrics, and
   completion-check fields. Use stable section/key order, canonical scalar
   formatting, no record text, secrets, exception strings, or raw content,
   and include `PENDING_AT_REPORT_COMPLETION` publication markers. Report
   counts and manifest metadata exactly; do not derive a dataset version or
   write `LATEST.txt` in M10-C.

4. Add adversarial tests for `None`, `object()`, wrong quality mode/type,
   both modes, malformed/extra manifest counts, duplicate JSON keys, NaN,
   schema-invalid records, count drift, non-empty initial tombstones,
   non-empty media/symbol/sync acceptance, unsafe report paths, validator or
   quality mutation/exception, report no-clobber and cleanup, deterministic
   repeated bytes, and M6G one-page golden compatibility.

No M10 CLI, publisher, connector, network, raw/checkpoint store, delta
export, or real external run is included. Use the existing staging writer and
validator; do not add a parallel writer or alter M6G models/CLI.
