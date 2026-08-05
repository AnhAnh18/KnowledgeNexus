RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-D/E Plan Critique

## Review posture

The repository currently has M10-A, M10-B, and M10-C implementation plus fresh
independent `PASS` evidence. The existing M3 writer/completer/publisher are the
authoritative filesystem seams. No M10 CLI/orchestrator, publication acceptance
readback, or M10 synthetic end-to-end test exists yet. `.local_ai` records M10-D
as next and M10-E as pending; M8-AC's real mini-corpus gate is explicitly
`pending_external_input`.

The safe meaning of "finish M10" is therefore: prove the bounded synthetic
full-snapshot CLI/publication contract (M10-D) and its synthetic acceptance
matrix (M10-E), obtain a fresh independent review `PASS`, and record that the
real operator full-POC gate remains `pending_external_input`. Synthetic output
must not be called a real Confluence/Git POC PASS, and this milestone must not
start delta export, indexing, retrieval, network access, or M8-AC evidence
fabrication.

## Requirements to lock before implementation

### 1. One explicit application/CLI boundary

Define one M10 application use case and one CLI entry point that accept a
runtime-validated `M10SnapshotRequest` (or a sanitized config factory) and
injected `M10ConfluenceAdapter`/`M10GitAdapter` ports. The CLI must not import
HTTP transports, Confluence credentials, Jira clients, raw/checkpoint stores,
or private M6G CLI state. Validate exact runtime types, enums, field sets,
paths, profile identity, and export mode before invoking adapters or touching
the filesystem. `None`, `object()`, path-like probes, forged dataclass
instances, and malformed nested config must fail closed with zero dependency
calls and no output artifacts.

The boundary needs a closed error mapping for every M10 failure category,
including `invalid_request` and `adapter`, not only the existing export
projection/staging/completion/publication/acceptance categories. Preserve the
M6G exit values 1-19 and its one-line sanitized JSON stderr vocabulary. A
generic unexpected exception must never include exception text, paths, IDs,
URLs, principals, content, hashes, or traceback data.

### 2. Derive quality data; do not trust caller counts

M10-C validates a typed `M10QualityReportInput`, but M10-D must construct that
input from the trusted `M10SnapshotProjection` and the actual stream records.
CLI/config values must not be able to lie about counts, relation statuses, ACL
coverage, media statuses, symbol resolution, sync cardinality, or tombstone
emptiness. Revalidate the canonical profile/config hash and loaded chunker
version at this boundary. Source scopes and generated timestamp must be copied
from the request/projection and compared byte-for-byte with the manifest.

Use `FullSnapshotStagingWriter` once with the eight projection streams, then
`FullSnapshotStagingCompleter.complete(..., m10_quality=...)`; do not add a
second writer or emit partial streams. The initial `tombstones` stream is
always empty. Media, symbols, and diagnostic sync streams may be populated,
but only when policy/provenance permits them.

### 3. Deterministic version and owned staging lifecycle

Use the existing `DatasetVersionGenerator`/M3 convention as the only source of
`vYYYYMMDD-HHMMSS-ffffffZ`; no caller-supplied folder name or arbitrary digest
may influence the path. Create an owned staging directory as a direct child of
the validated dataset root, reject existing staging/final entries, and clean up
only that owned directory on pre-publication failure. Enforce a plain,
non-symlink/non-reparse dataset root and direct-child containment before any
adapter or writer call. Keep generated-at deterministic for repeated fixture
runs (for example, an injected fixed instant) so byte comparison is meaningful.

The existing publisher renames staging to the final directory and only then
atomically replaces `LATEST.txt`. Its tested failure contract intentionally
allows an unadvertised final directory when the `LATEST` replacement fails,
while preserving the old pointer. M10 must either adopt and document this
contract or add a bounded compensating policy; it must not claim rollback of
the rename that the shared publisher does not provide. In every failure case,
the prior pointer must remain byte-identical and no existing final version may
be clobbered.

### 4. Publication acceptance is a separate postcondition

After `FullSnapshotPublisher.publish`, perform a read-only acceptance pass on
the returned final path and root pointer:

- exactly ten regular non-symlink files in the version directory (eight JSONL,
  `manifest.json`, `quality_report.md`) and no `LATEST.txt` inside it;
- strict JSON/JSONL parsing (duplicate keys and non-finite constants rejected),
  schema validation for every record, exact eight counts, manifest/folder
  dataset-version equality, and empty initial tombstones;
- manifest source scopes, profile/config/chunker metadata, report bytes, and
  all graph/ACL/relation/media/symbol/sync invariants equal the pre-publication
  projection; `LATEST.txt` contains exactly `<dataset_version>\n` and points to
  the verified directory;
- no post-completion mutation of report or machine files.

The M3 publisher itself only validates a manifest and complete file set. Do not
treat that as the full M10 acceptance gate. A failed post-publication readback
must map to `export_acceptance` (19), preserve the old pointer where possible,
and never report success.

### 5. Synthetic fixture must exercise every allowed stream

Use immutable in-memory adapters with non-empty Confluence and Git documents,
chunks, ACL records, and at least one relation. Include a policy-allowed media
asset with parent/raw provenance, a Git symbol that resolves to an emitted
chunk, and diagnostic `sync_state` rows covering page/attachment/file/repo
entity types. Keep `tombstones` explicitly empty. Include an unresolved Jira
relation with its explicit closed status/target grammar, not a fabricated Jira
record. Verify deterministic ordering and cross-source IDs.

Run the complete CLI twice against equivalent immutable fixtures and separate
roots (or a fixed version generator), then compare every stream byte, manifest,
quality report, counts, final file set, and pointer bytes. A second publication
into the same root must be a no-clobber failure, not an overwrite.

## Adversarial acceptance matrix

Every public/application boundary needs both happy-path and negative tests:

- malformed config: `None`, `object()`, wrong enum/status, missing/extra keys,
  wrong tuple/list/dict/path types, forged frozen models, unsafe root,
  symlink/reparse root, bad timestamp, bad commit, profile/hash drift, and
  `export_mode != full_snapshot`;
- adapter boundary: wrong result type, `None`, adapter exception/category
  leakage, generation/run/source-version drift, Git branch/commit/path drift,
  unexpected source ownership, duplicate IDs, forbidden streams, and any
  adapter call after an invalid request;
- projection/graph: schema-invalid records, malformed relation target or
  status, unresolved target silently dropped, missing/duplicate ACL, empty or
  inherited ACL mismatch, media parent/provenance/status/budget mismatch,
  symbol file/commit/line mismatch or missing chunk, sync entity/version drift,
  count mismatch, non-empty initial tombstones, and validator mutation or
  exception;
- staging/publication: existing staging/final paths, nested/sibling/outside
  roots, symlink entries, unexpected files, pre-existing/corrupt directory
  `LATEST.txt`, rename failure, `LATEST` temp/replace failure, report write or
  cleanup failure, no-clobber second run, and no leaked M3 logger traceback;
- acceptance/report security: duplicate-key/NaN JSON, post-publication file or
  report mutation, folder/LATEST mismatch, report containing record text,
  source IDs, URLs, paths, principals, secrets, hashes, or exception strings.

For each negative case assert the sanitized category/exit code, no stdout on
failure, no partial staging/report/LATEST side effects (except the shared
publisher's documented unadvertised final on post-rename `LATEST` failure),
and unchanged pre-existing files. Test wrong runtime types before field access
or side effects; annotations/dataclass construction alone are insufficient.

## Recommended bounded tests and commands

Add focused tests rather than broad unbounded integration:

```text
python -m pytest -q tests/foundation/application/use_cases/test_export_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10d-usecase
python -m pytest -q tests/foundation/cli/test_export_m10_snapshot_cli.py --basetemp=.codex-workflow/20260805-m10/pytest-m10d-cli
python -m pytest -q tests/foundation/integration/test_m10_synthetic_acceptance.py --basetemp=.codex-workflow/20260805-m10/pytest-m10e-synthetic
python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py --basetemp=.codex-workflow/20260805-m10/pytest-m10d-export
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10abc
python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-m6g
python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-m8m9
python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10-arch
python -m compileall -q src tests
git diff --check
```

The implementer must report exact commands/results and use a fresh independent
review session before roadmap/state changes. A real Confluence/Git invocation,
credentials, tokenizer assets, raw pages, or unsanitized evidence are outside
this synthetic gate.

## Acceptance and closeout decision

M10-D/E is ready for closeout only when the synthetic CLI proves deterministic
ten-file publication, exact graph/count/report/pointer invariants, atomic
failure/no-clobber behavior, and sanitized boundaries; all focused and
bounded-regression commands pass; and a fresh independent reviewer reports
`PASS`. The roadmap/state closeout should say:

`M10-A/B/C/D complete; M10-E synthetic acceptance complete; M8-AC real gate and
real M10 full-POC invocation remain pending_external_input.`

Do not claim a real M10 PASS, M8-AC PASS, delta readiness, or operator evidence
until the approved generation/scope, pinned assets, credential handling, and
sanitized aggregate report are supplied externally.
