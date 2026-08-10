# W1 implementer prompt — operator-runnable Confluence M10 snapshot

Hand this file to a codex implementer as one task. It is W1 of
`docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md`. Do not also hand W0
(already done, commit `d25ea42`) or W2.

---

## Task

Build one production composition plus operator CLI that turns a preserved
Confluence raw generation into a published M10 full snapshot with all eight
JSONL streams plus manifest.

Today there is **no way for an operator to produce an M10 snapshot at all**.
Every producer exists and is test-verified, but nothing wires them together
behind a runnable command. This task closes exactly that gap.

## Verified starting state — read before designing

These were confirmed by reading the code at `d25ea42`. Trust them, but
re-verify anything you intend to change.

1. `ConfluenceM10CompositionRoot` (in
   `src/knowledgenexus/foundation/infrastructure/adapters/m10_composition_root.py`)
   is referenced **only from tests**
   (`tests/foundation/infrastructure/adapters/test_m10_composition_root.py`).
   No production code constructs it.

2. `src/knowledgenexus/foundation/cli/export_m10_snapshot.py` **cannot be run
   from a shell**. Its `_parse_args` calls `parser.parse_args([])` and returns
   an empty `Namespace`; `request`, `confluence_adapter`, and `git_adapter` are
   Python-injected keyword arguments. `python -m
   knowledgenexus.foundation.cli.export_m10_snapshot` returns `invalid_request`
   (exit 20) because all three are `None`.

3. `ConfluenceM10CompositionRoot.build()` already constructs
   `ProcessConfluencePageSet` internally from `raw_page_store`, `tokenizer`,
   `chunking_profile`, `raw_page_mapper`, `storage_normalizer`,
   `schema_validator`. It accepts `relation_stage`, `acl_stage`, `media_stage`,
   `sync_inventory_stage` as **already-built** objects defaulting to `None` —
   it does **not** build them. Building them is the core of this task.

4. `GitM10CompositionRoot.build()` takes `repository_reader`, `tokenizer`,
   `repository_root`, `budgets` (`GitScanBudgets`), `case_policy`
   (`GitCasePolicy`), plus optional `symbol_parser`, `sync_inventory_stage`,
   `schema_validator`.

5. Producers that exist and must be composed, not reimplemented:

   | Stream | Producer |
   |---|---|
   | `documents`, `chunks` | `ProcessConfluencePageSet` (built by the root) |
   | `relations` | `BuildConfluenceJiraRelations`, `MaterializeConfluenceMediaRelations` |
   | `acl` | `MaterializeConfluenceAcl` |
   | `media_assets` | `ProcessConfluenceMediaAttachment` / `ProcessConfluenceMediaBatch` |
   | `sync_state` | `BuildSyncStateSnapshot` |
   | `tombstones` | `ProjectTombstones` |
   | handoff assembly | `AssembleConfluenceM10Handoff` |

6. **A Confluence-only snapshot is supported — this is settled, do not
   re-litigate it.** `M10SnapshotRequest` requires `git_repository`,
   `git_branch`, and `git_commit` (40-hex), and `M10GitHandoff.__post_init__`
   rejects an empty repository/branch or a non-hex commit. But a handoff
   carrying a **valid pinned Git identity with zero records in every stream
   publishes successfully.** Verified by running the real
   `M10FullSnapshotExporter` over `_handoffs()` with an all-empty
   `M10GitHandoff`: result `status == "published"`, counts
   `{documents: 1, chunks: 1, relations: 1, acl: 1, media_assets: 0,
   symbols: 0, sync_state: 1, tombstones: 0}`.

   So support a Confluence-only mode that pins a real repository/branch/commit
   and emits no Git rows. Do **not** weaken any validation to achieve this.

7. `M10SnapshotRequest` fields: `run_id`, `generation_id` (must equal
   `run_id`), `confluence_scope` (`M10ConfluenceScope`), `confluence_exclusions`,
   `ordered_page_ids`, `raw_generation_id`, `git_repository`, `git_branch`,
   `git_commit`, `media_policy` (`M10MediaPolicy`), `profile_bundle`
   (`OnePageExportProfileBundle` = `chunking_profile` + `jira_relation_profile`
   + 64-hex `config_hash`), `generated_at`, `dataset_root`, `export_mode`,
   `profile_identity` (`M10ProfileIdentity`, required), `base_dataset_version`.

   `M10ConfluenceScope` requires `space_keys`, `root_page_ids`, `page_ids` to
   each be non-empty, sorted, unique, NFC-normalized, and
   `root_page_ids ⊆ page_ids`.

8. The existing sanitized exit-code taxonomy in `cli/export_m10_snapshot.py`:
   `1` unexpected, `2` configuration, `20` invalid_request, `21` adapter,
   `15` projection, `16` staging, `17` completion, `18` publication,
   `19` acceptance. Keep it.

## What to build

### A. Confluence stage builders

Construct the four optional stages that `ConfluenceM10CompositionRoot.build()`
expects but does not create: relation, acl, media, sync inventory (and a
tombstone stage where the export mode needs one). Compose the approved use
cases listed above. Discover each one's real constructor and `execute`
signature from its module and tests — do not guess.

### B. An operator CLI

Either extend `cli/export_m10_snapshot.py` to parse real arguments, or add a
sibling CLI that delegates to it. Prefer the option that leaves the existing
injected `run(...)`/`main(...)` seam intact for tests.

It must accept real absolute-path arguments covering at minimum: raw
generation root, run id, generation id, chunking profile path, tokenizer
assets dir, Jira relation profile path, dataset root, ordered page ids (or a
selection path), Confluence scope (space key(s), root page id(s)), exclusions,
media policy, Git identity (repository/branch/commit), export mode, and
generated-at.

It must:

- validate every path is absolute and a plain file/directory chain, rejecting
  symlinks and reparse points — reuse
  `knowledgenexus.foundation.ports.path_safety`;
- never reach the network. This is an offline boundary over preserved raw
  evidence only;
- emit sanitized output only — no credentials, URLs, page ids, titles, content,
  paths, or full hashes — and keep the existing exit-code taxonomy;
- refuse to publish a partial or non-deterministic snapshot.

### C. Tests

- An offline test that publishes a full eight-stream snapshot plus manifest
  from fixture raw evidence, runs it **twice**, and asserts byte-level
  determinism and identical `dataset_version`/`digest`.
- A Confluence-only test (zero Git records, pinned Git identity) that publishes
  and reports `symbols: 0`.
- **Adversarial negative pass is mandatory** on the new CLI and composition
  boundary, per `AGENTS.md`: `object()`, `None`, wrong enum values, missing
  required fields, forbidden extra fields, impossible counters, relative paths,
  symlinked paths, `run_id != generation_id`, unsorted/duplicate scope tuples,
  non-hex `git_commit`. Type annotations and dataclass construction are not
  runtime validation.

## Constraints

- Compose existing approved seams. Do not reimplement HTTP, pagination,
  normalization, chunking, ACL, relation, media, sync, tombstone, or export
  logic.
- Do not weaken, bypass, or special-case any existing validation to make a
  test pass. If a contract genuinely blocks the task, **stop and report it**
  as a blocking question rather than working around it.
- Do not run live Confluence requests. Do not read, print, or commit `.env`,
  `.local_ai/evidence/`, `Tool_TRreport/`, raw runtime data, credentials, or
  unsanitized Confluence content.
- The pinned BGE-M3 tokenizer bundle is **not available on this machine**.
  Asset-backed tests will `pytest.fail` without `--tokenizer-assets-dir`;
  report those honestly as **not run**, never as failures, and never satisfy
  them with an implicit Hugging Face cache. Inject a tokenizer double in your
  own tests instead.
- Scope is Confluence text-first. No OCR, no PDF/image/audio/video, no
  `attachment_text` chunks, no scheduler/quarantine/retention work.

## Environment

```
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Run and report exact commands and results for:

```
python -m pytest tests/foundation tests/shared tests/architecture -q
```

Expected pre-existing baseline at `d25ea42`: **3264 passed, 40 skipped,
9 errors** in `tests/foundation` (all nine errors are the asset-backed BGE-M3
tests described above), plus **117 passed** in `tests/shared tests/architecture`.
Any new failure is yours.

## Definition of done

`python -m knowledgenexus.foundation.cli.<cli> --help` works, and an offline
test publishes a deterministic eight-stream snapshot plus manifest from a
preserved fixture generation — including a Confluence-only run with zero Git
records.
