# W2 implementer prompt — bind the subtree harness generation to the M10 request

Hand this file to a codex implementer as one task. It is W2 of
`docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md`. **W1 must be complete
first** — this task consumes the CLI that W1 builds.

---

## Task

The subtree harness (`cli/confluence_subtree_corpus.py`) *produces* a raw
generation. The W1 M10 CLI *consumes* one. Nothing yet proves they agree.
Prove it, enforce it, and fix whatever does not line up.

Today these are two halves that each work in isolation and have never been run
against each other.

## What must line up

1. **`ordered_page_ids`** — must be derived from the harness's
   `inventory-selection.json`, preserving its deterministic order and its
   run/generation and `selection_identity` binding. Not a hand-written list.

2. **`raw_generation_id`** and run/generation identity — the harness uses the
   run id as the generation id. The M10 request requires
   `run_id == generation_id`.

3. **Raw page layout** — the harness writes pages through
   `ConfluenceRawPageGenerationStore(raw_root=...)`; `ProcessConfluencePageSet`
   reads through the same class. **assumed compatible**, but confirm it rather
   than trusting the type name.

4. **Draw.io attachment layout** — this is the real risk. See below.

5. **Fail closed** on any mismatch of run id, generation id, fingerprint, or
   selection identity between harness state and the M10 request.

## The known blocker — read this before designing

**verified.** The M10 media path cannot currently be fed from raw attachment
evidence alone. Concretely:

- `ProcessConfluenceMediaBatch.execute(items=...)` requires tuples of
  `(MediaAttachmentBodyEnvelope, ConfluenceAttachmentObservation)`.
- The harness persists attachment bodies via
  `ConfluenceRawAttachmentStore(data_root=raw_root / "attachments")`, which
  stores envelopes at
  `{data_root}/confluence/attachments/{attachment_id}/{content_hash}.json`.
- `MediaAttachmentBodyEnvelope` carries only `format_version`,
  `evidence_kind`, `attachment_id`, `parent_page_id`, `filename`,
  `source_version`, `http_status`, `body_encoding`, `body_bytes`.
- `ConfluenceAttachmentObservation` additionally has `mime_type`,
  `size_bytes`, `source_version`, `updated_at` — all nullable, so those are
  survivable — **and `crawled_at: str = ""`, which is not.**
- `media_asset.schema.json` lists `crawled_at` as **required**, typed as a
  strict RFC 3339 timestamp. An empty string fails validation.

So reconstructing an observation from the envelope alone yields a
**schema-invalid** `MediaAsset`. `crawled_at` must come from somewhere.

Candidate sources, in rough order of preference:

- the harness's `inventory-selection.json`, which already carries a
  `crawled_at` per page (attachments belong to a parent page);
- the M10 request's `generated_at`;
- the harness's `drawio-state.json`, whose `media_assets` array already
  contains fully-formed asset records including `crawled_at`.

**Investigate and pick deliberately, then say which you picked and why in your
report.** Note the trade-off: the first two keep M10 re-deriving assets from
preserved raw evidence, which is the design intent stated at the top of
`application/use_cases/confluence_subtree_corpus.py`. The third makes M10 trust
harness-produced state instead of raw evidence — cheaper, but it weakens the
provenance story and would need to be justified explicitly.

If a fourth option turns out to be cleaner — for example persisting attachment
observations alongside the bodies at capture time — that is acceptable, but it
changes the harness's durable format and must be called out as such.

## Scope boundaries

- Do **not** silently change the harness's durable state formats
  (`inventory-selection.json`, `processing-state.json`, `drawio-state.json`).
  If a format change is genuinely required, state it plainly in your report,
  keep it additive and versioned, and preserve the existing no-clobber and
  replay-conflict behavior.
- Do not weaken `media_asset.schema.json` or any other contract to make this
  fit. If the contract genuinely blocks the task, **stop and report it**.
- Do not reimplement chunking, ACL, relation, media, or export logic.

## Tests

- **The forcing test.** One offline test that drives the harness end to end
  over a fake transport (no network) and then runs the W1 M10 CLI over the
  resulting generation, asserting the published snapshot's document and media
  counts match the harness packet. There must be no manual translation step
  between the two.
  `tests/foundation/cli/test_confluence_subtree_cli.py::test_five_phases_run_sequentially_against_one_state_dir_and_run_id`
  is a working model for the harness half — reuse its fake transport and
  injected-tokenizer approach.
- A test with at least one Draw.io attachment, so the media path is actually
  exercised rather than skipped on an empty reference set.
- Negative tests: run id mismatch, generation id mismatch, selection identity
  mismatch, and a raw generation missing a page the selection claims — each
  must fail closed.
- Adversarial negative pass on any new public boundary per `AGENTS.md`.

## Constraints

- Do not run live Confluence requests. Do not read, print, or commit `.env`,
  `.local_ai/evidence/`, `Tool_TRreport/`, raw runtime data, credentials, or
  unsanitized Confluence content.
- The pinned BGE-M3 tokenizer bundle is **not available on this machine**.
  Asset-backed tests `pytest.fail` without `--tokenizer-assets-dir`; report
  them as **not run**, never as failures, and never satisfy them with an
  implicit Hugging Face cache. Inject a tokenizer double in your own tests.
- Scope is Confluence text-first. No OCR, no PDF/image/audio/video.

## Environment

```
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Run and report exact commands and results for:

```
python -m pytest tests/foundation tests/shared tests/architecture -q
```

Baseline at `764efa3` (before W1): **3264 passed, 40 skipped, 9 errors** in
`tests/foundation` (all nine are the asset-backed BGE-M3 tests), plus
**117 passed** in `tests/shared tests/architecture`. W1 will have added to the
pass count; take your actual starting point from the W1 commit and report any
new failure as yours.

## Definition of done

One offline test proves: harness live phases → raw generation → M10 CLI →
published eight-stream snapshot, with Draw.io media flowing through, and no
manual step in between.
