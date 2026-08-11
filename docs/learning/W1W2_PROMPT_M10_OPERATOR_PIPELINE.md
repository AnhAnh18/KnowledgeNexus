# W1+W2 implementer prompt — operator-runnable Confluence M10 pipeline

Supersedes `W1_PROMPT_M10_OPERATOR_COMPOSITION.md` and
`W2_PROMPT_HARNESS_TO_M10_BINDING.md`. Those two are merged here because W1 as
originally written contained a scope error: it assumed a raw generation root
alone is sufficient input. **It is not** — enumerating Draw.io media requires
`attachment_id` and `content_hash`, which live in the harness's
`drawio-state.json`. Splitting that into W2 made W1 unbuildable. This prompt
fixes that.

Read `docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md` for context.

---

## Task

Make an operator able to run, from a shell, a preserved Confluence raw
generation plus its harness state into a published M10 full snapshot with all
eight JSONL streams and a manifest.

## Current state — a partial attempt exists, keep the good parts

An earlier attempt is in the working tree. **Keep these, they are correct:**

1. `cli/export_m10_snapshot.py` — the argparse surface (~21 options) and the
   `require_plain_directory_chain` / `require_plain_file` validation. Verified
   working.
2. `_media_policy()` mapping the operator vocabulary onto `M10MediaPolicy`,
   plus its test.
3. `ConfluenceM10CompositionRoot.build()` now raises
   `M10CompositionRootError` when `relation_stage` / `acl_stage` /
   `media_stage` is `None`. **Fail-closed is the right call — keep it**, and
   extend it to `sync_inventory_stage`, which is currently unchecked and can
   still yield a silently empty `sync_state` stream.

**These are the two things that must change:**

- **The CLI parses arguments and then discards them.** `main()` assigns
  `parsed = _parse_args(...)`, reads exactly one field for validation
  (`_media_policy(parsed.media_policy)`, whose return value is thrown away),
  then falls through to `if request is None ... raise invalid_request`.
  Running it from a shell with every argument supplied still returns
  `{"category": "invalid_request", "status": "failed"}`, exit 20 — **verified
  by execution**. Nothing builds an `M10SnapshotRequest` or the adapters.
- **No producer is composed.** All eight of `MaterializeConfluenceAcl`,
  `BuildConfluenceJiraRelations`, `MaterializeConfluenceMediaRelations`,
  `ProcessConfluenceMediaBatch`, `ProcessConfluenceMediaAttachment`,
  `BuildSyncStateSnapshot`, `ProjectTombstones`,
  `AssembleConfluenceM10Handoff` appear zero times in the changed files. An
  earlier ACL stage was written by hand, always raised, and was then deleted
  rather than corrected — so the Confluence path currently emits no ACL at all.

## Inputs the CLI must accept

Both of these, together — this is the correction to the original W1 scope:

- the **raw generation** root (pages and attachments), and
- the **harness state** directory or its individual artifacts:
  `inventory-selection.json`, `processing-state.json`, `drawio-state.json`.

`ordered_page_ids` must be derived from `inventory-selection.json`, preserving
its order and its run/generation and `selection_identity` binding — not passed
as a hand-written list. Fail closed on any run id, generation id, or selection
identity mismatch between harness state and the request.

## The stage contract — read this before designing

**verified.** `ConfluenceM10MaterializedSource.collect()` calls each stage
through `_stage_call(stage, request=request, state=state)`, and
`_invoke_stage_callable` **inspects the callable's signature and passes only
the matching names**. A stage may be the approved use case itself, or a thin
facade around it.

State keys available to stages: `documents`, `chunks`, `page_references`,
`page_targets`, `reference_intents_by_page`, `media_assets`, `sync_inventory`,
`media_result`, `media`.

Stage order in `collect()` is fixed and deliberate: **media → acl → relation →
tombstone → inventory**. Media runs first so relation stages can resolve
attachment intents against the current asset set; generic relations run after
ACL so their IDs land on the ACL-enriched records.

Consequences you can exploit:

- `MaterializeConfluenceMediaRelations.execute(*, documents, chunks, media,
  page_references=(), page_targets=())` — every parameter is already a state
  key. It can be injected directly with no wrapper.
- `BuildSyncStateSnapshot.execute(*, source_id, synced_at, documents,
  media_assets=(), repository_id=None, repository_version=None,
  inventory=None)` — `source_id` and `synced_at` are not state keys, so this
  one needs a thin facade that supplies them from `request`.

## The ACL unblock — this is not blocked, do not skip it

The previous attempt reported that ACL could not be composed because the raw
generation carries no restriction observations. **That is incorrect.**
`MaterializeConfluenceAcl` is explicitly designed for that case. **verified by
reading `_decide_policy`:**

```
# Any unavailable observation → deny-safe unavailable
if facts.has_unavailable:
    return _AclPolicy(
        is_restricted=True,
        acl_tags=list(_DEFAULT_DENY_TAGS),      # ["restricted:unresolved"]
        acl_extraction_status="unavailable",
        acl_confidence="approximate",
        reason_codes=("restriction_observations_unavailable", ...),
    )
```

`_DEFAULT_DENY_TAG = "restricted:unresolved"` — exactly the contract's
default-deny materialization.

A restriction observation is a mapping with keys
`{"source_page_id", "http_status", "classification", "users", "groups"}`, and
`"unavailable"` is a valid `classification`. So supplying one `unavailable`
observation per page yields a contract-correct, deny-safe `ACLRecord` through
the approved producer.

`MaterializeConfluenceAcl.execute(*, jira_relation_result,
restriction_observations, crawler_identity, extracted_at)` needs a
`ConfluenceJiraRelationResult`, so the ACL facade must run
`BuildConfluenceJiraRelations` first and pass `extracted_at` /
`crawler_identity` from the request.

**Do not hand-roll an ACL record.** Compose the approved producer.

## The media blocker — real, and here is the shape of it

**verified.** `ProcessConfluenceMediaBatch.execute(items=...)` requires tuples
of `(MediaAttachmentBodyEnvelope, ConfluenceAttachmentObservation)`.

- Envelopes are in `ConfluenceRawAttachmentStore` at
  `{raw_root}/attachments/confluence/attachments/{attachment_id}/{content_hash}.json`,
  readable via `read_attachment(attachment_id=, content_hash=)`. Reading one
  requires knowing both ids — **they come from `drawio-state.json`**, whose
  `media_assets[].raw_uri` has the form
  `raw://confluence/attachments/{attachment_id}/{content_hash}`. This is
  precisely why harness state is now an input.
- `ConfluenceAttachmentObservation` has `mime_type`, `size_bytes`,
  `source_version`, `updated_at` all nullable — survivable — **and
  `crawled_at: str = ""`, which is not.** `media_asset.schema.json` requires
  `crawled_at` as a strict RFC 3339 timestamp; an empty string fails
  validation.

Candidate sources for `crawled_at`, in rough order of preference:
`inventory-selection.json`'s per-page `crawled_at` (an attachment belongs to a
parent page); the request's `generated_at`; or the `crawled_at` already present
in `drawio-state.json`'s asset records.

**Pick deliberately and say which you picked and why in your report.** The
first two keep M10 re-deriving assets from preserved raw evidence, which is the
stated design intent. The third makes M10 trust harness-produced records
instead of raw evidence — cheaper, but it weakens provenance and needs explicit
justification.

## Hard rules

- **Wire the parsed arguments through.** Build a real `M10SnapshotRequest` and
  real adapters from them. A CLI that validates arguments and then demands
  Python-injected objects has not done this task.
- **Do not delete a stream to make the build pass.** If a stage cannot be
  composed, stop and report it — do not remove it and publish seven streams.
  The previous attempt deleted ACL rather than fixing it.
- **Do not hand-roll a producer.** Compose the approved use cases. If one
  genuinely cannot be driven from preserved evidence, report that as a blocking
  question with the specific missing input named.
- **Do not weaken or special-case any validation** to make a test pass. If a
  contract blocks the task, stop and report it.
- Keep `M10ConfluenceScope` correct: `space_keys`, `root_page_ids`, `page_ids`
  each non-empty, sorted, unique, NFC-normalized, `root_page_ids ⊆ page_ids`.
- Keep the sanitized output and the exit-code taxonomy (`1` unexpected,
  `2` configuration, `20` invalid_request, `21` adapter, `15` projection,
  `16` staging, `17` completion, `18` publication, `19` acceptance).
- Never reach the network. This is an offline boundary over preserved evidence.
- A Confluence-only snapshot is supported and settled: pin a real
  repository/branch/commit and emit zero Git records. **verified** — the real
  `M10FullSnapshotExporter` publishes such a handoff. Do not weaken validation
  to achieve it.

## Tests — `--help` is not evidence

The previous attempt added one test asserting three booleans. That is not
coverage.

Required:

1. **The forcing test.** Drive the harness end to end over a fake transport
   (no network), then invoke the CLI **through `main(argv)` with a real
   argument list** over the resulting generation and harness state, and assert
   a published eight-stream snapshot plus manifest. It must fail if the CLI
   stops wiring its parsed arguments through.
   `tests/foundation/cli/test_confluence_subtree_cli.py::test_five_phases_run_sequentially_against_one_state_dir_and_run_id`
   is a working model for the harness half — reuse its fake transport and
   injected-tokenizer approach.
2. **Determinism.** Publish twice; assert byte-identical output and identical
   `dataset_version` / `digest`.
3. **Confluence-only.** Zero Git records with a pinned Git identity; assert
   `symbols: 0` and a published result.
4. **At least one Draw.io attachment** flowing through, so the media path is
   exercised rather than skipped on an empty reference set.
5. **ACL assertion.** With no restriction evidence, assert the emitted
   `ACLRecord` has `acl_tags == ["restricted:unresolved"]`,
   `acl_extraction_status == "unavailable"`, and `is_restricted is True`.
6. **A positive-path test for `ConfluenceM10CompositionRoot.build()`.** There
   is currently none — the only existing test passes `object()` and dies at
   processor construction before reaching the stage checks, so the fail-closed
   guard is itself untested. Cover both the success path and each
   missing-stage rejection.
7. **Negative tests:** run id / generation id / selection identity mismatch
   between harness state and request; a raw generation missing a page the
   selection claims; relative and symlinked paths.
8. **Adversarial negative pass** per `AGENTS.md` on every new public boundary:
   `object()`, `None`, wrong enum values, missing required fields, forbidden
   extra fields, impossible counters, non-hex `git_commit`,
   `run_id != generation_id`, unsorted/duplicate scope tuples. Type
   annotations and dataclass construction are not runtime validation.

## Scope

Confluence text-first. No OCR, no PDF/image/audio/video, no `attachment_text`
chunks, no scheduler/quarantine/retention. `export_mode="full_snapshot"` only —
the second-sync delta is W4 and has its own prompt.

Do not read, print, or commit `.env`, `.local_ai/evidence/`, `Tool_TRreport/`,
raw runtime data, credentials, or unsanitized Confluence content. Do not run
live Confluence requests.

## Environment

```
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

The pinned BGE-M3 bundle is **not on this machine**. Asset-backed tests
`pytest.fail` without `--tokenizer-assets-dir`; report them as **not run**,
never as failures, and never satisfy them with an implicit Hugging Face cache.
Inject a tokenizer double in your own tests.

Run and report exact commands and results for:

```
python -m pytest tests/foundation tests/shared tests/architecture -q
```

Baseline with the current partial attempt in the tree: **3265 passed, 40
skipped, 9 errors** in `tests/foundation` (all nine asset-backed BGE-M3), plus
**117 passed** in `tests/shared tests/architecture`. Any new failure is yours.

## Definition of done

A shell command over a preserved generation plus harness state publishes a
deterministic eight-stream snapshot and manifest, proven by an automated test
that goes through `main(argv)` with a real argument list.

`--help` exiting 0, or a CLI that still requires injected Python objects, does
not satisfy this.

## Reporting

State plainly what you built, what you did not, and why. Do not describe a
validation-only call as "using the parsed result", and do not describe deleting
a stage as fixing it. If something is genuinely blocked, name the specific
missing input — an accurate blocker report is more useful than an
overstated completion.
