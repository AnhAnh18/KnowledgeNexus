# M10-D/E Synthetic Publication - Final Plan

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Objective

Complete the bounded M10-D CLI/publication boundary and M10-E synthetic
acceptance. This does not claim a real Confluence/Git POC or close the M8-AC
real gate.

## Implementation

- Add one generic M10 export use case that accepts an exact validated
  `M10SnapshotRequest`, injected Confluence/Git adapters, canonical validator,
  export root, and deterministic generated timestamp.
- Compose through the existing `ComposeM10Snapshot`, derive all quality
  metrics from actual projection streams, and reject metric/provenance drift.
- Reuse `DatasetVersionGenerator`, `FullSnapshotStagingWriter`,
  `FullSnapshotStagingCompleter(m10_quality=...)`, and
  `FullSnapshotPublisher`; do not add parallel writer/publisher/version code.
- Add a sanitized M10 CLI entry point for the offline synthetic boundary. It
  must reject malformed inputs before adapter/filesystem side effects, map all
  failure categories to stable exit codes, and never import network,
  credentials, raw stores, or checkpoint state.
- Add post-publication readback acceptance for the exact ten-file snapshot,
  strict JSON/JSONL/schema validation, folder/manifest/LATEST consistency,
  projection equality, report immutability, and no-clobber behavior.
- Add synthetic fixtures with non-empty Confluence/Git streams, relation,
  ACL, media, symbol, page/attachment/file/repo sync rows, and empty initial
  tombstones. Run two equivalent exports and compare all bytes.

## Tests and validation

Add adversarial application/CLI/publication tests for `None`, `object()`,
forged requests, unsafe roots, adapter failures/wrong handoffs, schema and
provenance drift, duplicate IDs, existing final/LATEST paths, symlinks,
rename/LATEST failures, post-publication mutation, and sanitized output.
Run focused M10-D/E, M10-A/B/C, M6G, M8/M9, architecture, compileall, and
diff-check suites. Produce implementation report, then fresh independent
review; only after `PASS` update roadmap/state and commit/push.

## Non-goals

No live network/Confluence/Git run, credentials, tokenizer assets, raw
production evidence, delta export, indexing, retrieval, or M8-AC gate claim.
