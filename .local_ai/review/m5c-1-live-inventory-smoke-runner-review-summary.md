# M5C-1 Live Inventory Smoke Runner Review Summary

## Scope

M5C-1 adds an operator smoke harness that composes the approved production
components and nothing else:

- `src/knowledgenexus/foundation/cli/__init__.py`
- `src/knowledgenexus/foundation/cli/confluence_inventory_smoke.py`
- `tests/foundation/cli/test_confluence_inventory_smoke.py`
- `docs/runbooks/M5C_CONFLUENCE_INVENTORY_SMOKE.md`

No HTTP, CQL, pagination, parsing, normalization, scope policy, or report
serialization is duplicated. No production code was modified. No dependency was
added. No live request was made on this machine.

Patch type: **full/squashed**, applies on top of the pushed `main` (M5B-2 at
`a2fe824`). It is not incremental and depends on no earlier unmerged patch.

## Decisions applied

- Placement is `foundation/cli/`, not a new top-level `tools/` and not
  `presentation/cli/`. Runnable as
  `python -m knowledgenexus.foundation.cli.confluence_inventory_smoke`.
  Rationale: the runner is a composition root that must construct the concrete
  transport, adapter, and report writer, so hosting it under `presentation`
  would create a new `presentation -> foundation.infrastructure` edge. D34 lists
  only `presentation -> application use cases` as allowed, and v7.5 states that
  the dependency direction — not folder presence — is what holds from the first
  file. D35 also names `foundation/cli/` for crawl/export jobs and gives
  `presentation/` only an `api/` subtree. Under `foundation/cli/` the runner
  creates zero cross-context edges.
- Credentials come only from `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT`. The PAT
  has no CLI flag, is never printed, and is never persisted. `.env` is never
  loaded.
- `--output-dir` must be outside the repository working tree, exist, be a
  directory, and be empty. Repo containment is checked with `os.path.normcase`
  so the Windows check is case-insensitive.
- `page_size` and `max_search_pages` are positive actual integers via argparse;
  `max_search_pages` is passed to the approved adapter unchanged.
- Root labels are **not** requested. M5B-2 remains untouched. The summary states
  `root_labels_requested: false` and
  `root_labels_interpretation: "unknown_not_requested"`, and the runbook records
  that the root's empty labels cell is not authoritative and must not drive
  exclude-subtree choices.
- `m5c_smoke_summary.json` is success-only. Failure writes one sanitized JSON
  object to stderr and returns a category-specific exit code.

## Verification performed before success

Counts, root-uniqueness, scope-sum, and the attachment-unknown invariant are
checked on the items; then **both reports are reopened from disk** — the
writer's return value is its own input count and is not treated as evidence.
JSONL is parsed line by line; CSV is parsed with `csv.reader` and its header is
compared to `CSV_COLUMNS`. Report files are scanned for the exact PAT and for
header-shaped credential patterns. SHA-256 hashes are computed from the final
published bytes.

## Independent review fixes applied

The first independent review returned two P1 and one P2. All three were
reproduced locally before being accepted, and all three are fixed.

- **P1 — argparse echoed argv, including a mistyped PAT.** `ArgumentParser.error()`
  writes the offending arguments to stderr before raising, and `main()` caught
  `SystemExit` only afterwards, so `--pat <token>` printed the token verbatim.
  Probe confirmed `PAT leaked -> True`. Fixed with `_SanitizedArgumentParser`,
  which overrides `error()` — the funnel for every parse failure — to raise
  `SmokeFailure(configuration)` instead of printing. `--help` still works because
  it prints only argparse's own text and never argv. Re-probe: `PAT leaked ->
  False`, stderr is the sanitized JSON object, `--help` exits 0.

- **P1 — a failed run could leave a complete `status: passed` summary.**
  `created_paths.append(summary_path)` ran *after* `write_bytes()` returned, so a
  failure in the flush/close window left an untracked, fully written summary while
  the runner reported `failed`. That directly broke the runbook's claim that the
  summary's presence proves the run passed. Fixed by `_publish_summary` (see the
  round-2 entry below for its final, no-clobber form).

- **P2 — the runner could report pass with writer temp files still present.** The
  M5A writer swallows failures when removing its own temporaries, and the runner
  only checked its two target reports. Leftover
  `.pages_inventory.jsonl.<random>.tmp` files hold a second copy of real
  inventory metadata. Fixed by `_require_exact_output_tree`, which fails closed
  unless the directory holds exactly the expected files as regular non-symlink
  entries. Those temporaries are **writer-owned**, so they are left for
  the operator rather than deleted, per the "clean only runner-owned files" rule;
  the runbook now says to inspect the output directory after any failure.

### Round 2: one P1 regression introduced by the round-1 fix

The round-1 fix over-corrected. Registering a **pathname** in `created_paths` is
not acquiring **ownership** of that file, and the round-1 wording
("both paths owned before either can exist") was simply wrong. Two concurrent
creators were reproduced before the finding was accepted:

- Registering `jsonl_path`/`csv_path` *before* the writer ran meant that when a
  concurrent creator won the race, the writer correctly refused to clobber, and
  then this runner's cleanup deleted **that process's file**. Probe:
  `exit=8, concurrent_report_survived=False`.
- `os.replace()` silently overwrote a summary another process had just created.
  Probe: `exit=0, was_overwritten_by_passed_summary=True`. The fixed temp name
  `.m5c_smoke_summary.json.tmp` had the same collision risk between two runners.

Fixed by mirroring the M5A report writer, which already had this right:

- Report targets are registered **only after the writer returns successfully**.
  The writer publishes with an atomic no-clobber link and rolls back its own
  links on failure, so before it returns those paths may not be ours. This
  restores the pre-round-1 ordering, which was correct.
- `_publish_summary` creates its temporary through
  `tempfile.NamedTemporaryFile(delete=False)` — a unique, exclusively created
  name — and registers it the moment it exists, so the flush/close window that
  motivated round 1 stays covered.
- Publication uses `os.link` (no-clobber). `FileExistsError` means another
  process owns the name: fail closed, never replace, and never register it.
  `summary_path` joins `created_paths` only after the link succeeds.
- `_require_exact_output_tree` now also runs after publication, so the runbook's
  "exactly three files" is a verified postcondition rather than a claim.

Re-probing both scenarios inverts them: `concurrent_report_survived=True` and
`was_overwritten_by_passed_summary=False`, with the concurrent file byte-intact.
Four regression tests cover concurrent report creation, concurrent summary
creation, unique per-run temp names, and a failure occurring after the summary is
already published.

### Round 3: one P2, a vacuous regression test

`test_summary_publish_failure_leaves_no_temp_behind` claimed to exercise the
summary publisher but never reached it. `os` is a shared module object, so
patching `smoke.os.link` also replaced the link the M5A writer uses; the run
failed at the writer's first link and exited `8/report_write`. Probe:
`exit=8, _publish_summary called 0 times, first refused link =
pages_inventory.jsonl`.

The `== 8` assertion should have been the tell — a test named for the summary
publisher cannot legitimately end in `report_write`. The shared-`os` behaviour
was even documented in the adjacent `test_summary_temp_name_is_unique_per_run`,
so this was a failure to apply a known fact, not to discover one.

Fixed: the wrapper refuses only a link whose destination is
`m5c_smoke_summary.json` and delegates the writer's report links to the real
`os.link`; the expected exit is now `9/report_verification`; and the test asserts
`_publish_summary` actually ran before asserting the directory is empty. A
mutation check confirms the test has teeth — dropping the temp registration
leaves `.m5c_smoke_summary.json.<random>.tmp` behind and the assertion catches it.

## Deliberate engineering decisions worth review attention

1. **CSV rows are counted logically, not by line.** `_render_csv` uses
   `csv.DictWriter`, and real titles/paths may contain commas, quotes, or
   newlines, so `len(lines) - 1` would be wrong. A regression test injects a
   title containing a newline and a quote and asserts the physical line count
   exceeds the logical record count while the summary still reports 4.

2. **The summary's safety check is an allowlist, not a text denylist.** Keys must
   equal the allowlist and values must be integers, booleans, fixed literals, or
   64-char hashes. Source ID, space key, root page ID, and excluded page IDs are
   therefore excluded *structurally*. They are deliberately **not** also matched
   as text: a numeric page ID such as `1000` collides with a count, a limit, or a
   hex substring of a SHA-256 hash, which would fail a legitimate run. The PAT
   and base URL *are* matched as text because they are long and cannot collide.

3. **Output scanning uses header-shaped patterns**, `Authorization: Bearer` and
   `Set-Cookie:`, not the bare words. A real page may legitimately be titled
   "Authorization Guide", and the reports are expected to hold real inventory
   metadata; scanning for bare words would fail valid runs.

4. **Transport failure categorisation reads sanitized message literals.**
   `UrllibConfluenceHttpTransport` raises one error type with no status code and
   no typed cause, so `connection` cannot be distinguished from
   `authentication_or_http` by type alone. `_TRANSPORT_MESSAGE_CATEGORIES`
   mirrors the transport's own literals and is documented as such. If a later
   reliability task introduces typed transport failures, this mapping should be
   replaced. This is the one intentional coupling in the patch.

5. **`BaseException` is caught at the top of `main`.** An original exception may
   carry the URL, host, CQL, identifiers, titles, payload, or credential, so it
   must never reach stderr. Everything unrecognised becomes category
   `unexpected` with exit code 1.

## Tests

40 focused tests, all offline. An autouse fixture replaces
`urllib.request.build_opener` and `urlopen` in the transport module with a
raising stub, so no test can open a connection even by mistake.

Only the transport seam is faked: the **real** adapter, mapper, use case, and
report writer execute, and the test asserts the exact approved M5B-2 request
shape (`expand=space,version`, the `ancestor` CQL, numeric `limit`/`start`) is
produced by production code rather than by the harness.

Covered: three-file success output; production composition; M5A writer output
shape; summary counts/depth/flags; reopened row counts; logical CSV counting;
hashes matching published bytes; summary carrying no source/scope/connection/
secret value; deterministic strict JSON; missing base URL; missing PAT; PAT
rejected on the CLI; output dir inside the repo; repo root itself; missing,
non-directory, and non-empty output paths; failed inventory writing no summary;
transport failures mapped to stable categories; response-contract failure;
pagination-budget exhaustion; sanitized failure output; sanitized unexpected
error; attachment-count invariant; verification failure removing only
runner-owned files; positive-integer argument validation; argv never echoed on a parse error; `--help` still returning 0; a completed-then-raising summary publish leaving nothing behind; leftover writer temporaries failing closed; an unexpected output entry failing closed; a concurrent creator's report surviving cleanup; a concurrent creator's summary never being clobbered; per-run unique summary temp names; a failure after publication still removing the summary.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/cli -q
40 passed in 2.32s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/confluence tests/foundation/application/use_cases tests/foundation/infrastructure/exporters tests/foundation/integration -q
261 passed in 6.29s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
638 passed in 9.08s

git diff --check          PASS (exit 0)
git diff --cached --check PASS (exit 0)
git apply --reverse --check --cached m5c-1-live-inventory-smoke-runner.patch  PASS (exit 0)

PYTHONPATH=src python -m knowledgenexus.foundation.cli.confluence_inventory_smoke --help
  entrypoint resolves; PAT appears only in the text stating it is not accepted on the CLI

PYTHONPATH=src python -m ... (with CONFLUENCE_* unset)
  {"category": "configuration", "cleanup_incomplete": false, "status": "failed"}
  exit=2
```

638 = 598 pre-existing + 40 new. No existing test changed.

Real-identifier scan over the patch: `confluence-mx`, `sec.samsung`,
`938880621`, `SVMC`, `2840369320` all 0.

## Boundary confirmation

No environment loading beyond the two documented variables, no `.env`, no
retry/sleep/rate-limit/checkpoint/resume, no page body, no attachment, no ACL or
permission retrieval, no export/M3, no SyncStateRecord, no schema change, no
dependency, no M3/M4 change, no M5A/M5B production change, no live network call,
and no generated live data in the repository.

## Open follow-up, not part of this patch

- M5B-2 review findings P3-1 (unreachable `next_start <= page.start` branch),
  P3-2 (`page_size` above the deployment search cap), and P3-4 (transport accepts
  traversal paths) remain unresolved. None blocks M5C-2.
- `ROADMAP.md` still needs M5B-2 flipped from "implemented; review pending" to
  done following its approval.
