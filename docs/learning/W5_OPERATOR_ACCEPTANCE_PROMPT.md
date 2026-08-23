# W5 implementer/operator prompt — real-input Foundation acceptance

`RECOMMENDED_IMPLEMENTATION_PROFILE: complex`

W5 is a staged real-input acceptance and closeout task. This prompt does not
authorize a live Confluence request by itself.

## 0. Execution topology and role separation

This prompt is read by a source-review/local implementation agent running in:

```text
D:\Claude\KnowledgeNexus
```

That agent is not the main-machine operator and must never receive, request,
read or use the main-machine credentials, raw-data paths or unsanitized
evidence.

Roles are locked:

```text
LOCAL_IMPLEMENTATION_AGENT
  reviews the plan, prepares/tests runbooks, commits portable artifacts,
  prepares exact main-machine execution prompts, and reconciles returned
  sanitized evidence.

MAIN_MACHINE_OPERATOR
  applies the approved transfer/runbook, performs separately authorized W5-B
  and W5-C executions, and returns sanitized evidence packets.

OWNER
  supplies main-machine values directly to the main-machine operator and grants
  each live authorization.

INDEPENDENT_REVIEWER
  reviews the final A-through-D code/runbook/evidence range without editing.
```

The local implementation agent may own one goal covering W5-A through W5-D,
but that goal must wait at the W5-B/W5-C external-execution gates. Waiting for
main-machine evidence is not permission to emulate, fabricate or replace it.

## 1. Frozen base and repository identities

```text
SOURCE_REVIEW_W4_HEAD=cec2a8cc44e36f1ef38988207ebccf6287d7245f
W4-A/W4-B/W4-C1/W4-C2=approved
open P0/P1/P2=none
```

The source-review and main-machine repositories may have unrelated commit
histories. Keep these identities distinct:

```text
SOURCE_REVIEW_HEAD
MAIN_TRANSFER_HEAD
MAIN_EXECUTION_HEAD
```

Do not require their SHAs to match. Before a main-machine run, prove scoped
blob equivalence for every transferred W4 production/contract/test path.

## 2. Required reading

Read completely before preparing a runbook:

```text
AGENTS.md
contracts/foundation/START_HERE.md
contracts/foundation/DELTA_SECOND_SYNC_SPEC.md
contracts/foundation/CRAWL_RELIABILITY_SPEC.md
contracts/foundation/RETRY_POLICY_SPEC.md
contracts/foundation/RAW_GENERATION_SPEC.md
config/foundation/embedding_profile.yaml
config/foundation/crawl_reliability_profile.yaml
docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md
docs/learning/CONFLUENCE_AUTOMATION_READINESS.md
docs/learning/W1W2_PROMPT_M10_OPERATOR_PIPELINE.md
docs/learning/W4_PROMPT_DELTA_SECOND_SYNC.md
src/knowledgenexus/foundation/cli/confluence_subtree_corpus.py
src/knowledgenexus/foundation/cli/export_m10_snapshot.py
src/knowledgenexus/foundation/application/use_cases/capture_delta_inventory.py
src/knowledgenexus/foundation/infrastructure/exporters/delta_snapshot_reader.py
src/knowledgenexus/foundation/infrastructure/exporters/m10_snapshot_exporter.py
tests/foundation/cli/test_w4_c2_composition.py
```

Inspect nearby production models, stores, ports and tests when routed there.
Discover current CLI signatures from code; historical examples are not
authority.

Never read, print, commit or transmit `.env`, `.local_ai/evidence/`,
`Tool_TRreport/`, raw/runtime content, credentials or unsanitized Confluence
data.

## 3. Goal and exclusions

Prove on approved real Root-1 input, text-first:

```text
controlled live subtree capture
-> durable raw generation and resume
-> page normalization/chunking plus Draw.io only
-> deterministic full M10 snapshot
-> controlled second sync
-> evidence-bound sparse delta
-> strict effective-overlay readback
```

Out of scope: OCR, PDF/image extraction, audio/video, embeddings, Qdrant,
retrieval, scheduler, quarantine, retention, concurrency and Root 2/HQ.

## 4. Mandatory stages

### W5-A — inspection, transfer proof and runbook candidate

No live request.

1. Verify the frozen W4 source head and clean tracked source tree.
2. Identify the main-machine transfer head and prove scoped blob equivalence.
3. Inspect existing Root-1 external artifacts by metadata only.
4. Verify the explicit pinned BGE-M3 bundle; never use an implicit cache or
   download it.
5. Inspect `EvaluateBoundedMediaCorpusAcceptance`. If it requires all media
   kinds, stop and report a contract gap. Do not silently weaken it for
   Draw.io-only acceptance.
6. Prepare separate W5-B and W5-C runbooks. Parse-check only; do not execute.
7. Run the complete offline preflight matrix, including asset-backed tests when
   the explicit bundle exists.
8. Stop for owner confirmation and the separate W5-B live authorization. A
   separate independent code/evidence review is not required at this boundary.

Default W5-A changes are documentation/runbook only. If production code needs
a fix, stop and propose a separate bounded implementation/review task.

### W5-B — controlled Root-1 capture and full snapshot

Requires separate explicit owner authorization after W5-A approval.

The local implementation agent prepares the reviewed W5-B execution packet but
does not execute it. The owner transfers it to the main-machine operator. The
local agent resumes only after receiving an aggregate sanitized result/evidence
packet.

Reuse the existing phases; create no new crawler:

```text
inventory
capture-pages
process-pages
capture-drawio
export
export_m10_snapshot --export-mode full_snapshot
```

Requirements:

- Credentials exist only in the controlled live process environment and are
  cleared before offline processing/export.
- Use the active M7 reliability profile and explicit tokenizer bundle.
- Text plus Draw.io only; do not enable generic image/PDF/audio/video paths.
- Prove controlled stop after committed batches and explicit resume of the
  same run; committed inventory windows/pages are not fetched again.
- No automatic operator retry; bounded internal M7 retries remain active.
- Preserve valid partial raw/checkpoint artifacts on failure.
- Process/export offline with sockets forbidden.
- Publish twice from the same preserved generation into separate fresh roots
  using identical semantic inputs and generated-at.
- Require byte-identical version directories, dataset version and digest.
- Strict-read all eight streams, manifest counts, cross-stream closure,
  `LATEST.txt`, atomic publication and absence of staging residue.
- Raw/state inputs remain byte-identical.
- Stop after the one authorized live sequence. Continue to W5-C only after the
  owner inspects the sanitized W5-B outcome and grants a new W5-C live
  authorization.

### W5-C — controlled real second sync and sparse delta

Requires a new explicit owner authorization after W5-B approval.

The local implementation agent prepares the reviewed W5-C execution packet but
does not execute it. All real paths, credentials and source-state details stay
between the owner and main-machine operator.

The agent must not modify/delete Confluence pages, restrictions or content.
Any controlled source changes are performed and attested by the owner or an
authorized administrator outside the runbook.

Require an owner-approved safe scenario containing, where safely available:

```text
one content-changed page
one approved source-deleted/404 case
one access-revoked/403 case
one moved-out-of-scope case
one ACL-only change
```

If required cases cannot be established safely, stop and record the pending
gate. Never fabricate dispositions or use operator-authored status JSON.

Run:

```text
second complete inventory/capture generation
capture-delta-inventory
offline export_m10_snapshot --export-mode delta
strict delta/base overlay readback
```

Require:

- exact binding to the W5-B accepted base dataset version;
- missing-page probes only after complete inventory;
- status/body evidence before `delta-inventory.json`;
- matching replay zero GET and conflict fail-closed;
- exact 404 ambiguity detail, 403 access-revoked, 401/retry failure;
- still-in-scope 200 missing from inventory fails inconsistent;
- socket-forbidden offline delta export;
- genuinely sparse rows/tombstones and valid effective overlay;
- cascade to chunks/media/relations/ACL;
- ACL-only emits ACL and affected chunks without content tombstone;
- unchanged repeat produces a valid empty delta;
- deterministic repeat into fresh roots;
- all base/raw/state inputs unchanged.

### W5-D — evidence reconciliation and closeout candidate

Begin only after W5-B and W5-C have completed under their separate owner
authorizations and their sanitized local evidence is available.

The owner transfers only the sanitized evidence packet back to the local
implementation agent. The local agent must not request raw logs, raw sidecars,
page IDs, filesystem paths, credentials or unsanitized Confluence content.

Documentation-only. Update the active learning/readiness state and portable
milestone status. Record capabilities/milestones as portable truth; keep
repository-specific SHA mappings in local provenance only.

Do not claim unattended recurring-crawl readiness. W5 closes Confluence
Foundation text-first correctness; scheduling, quarantine, retention,
observability and concurrency remain future Automation Readiness work.

## 5. Runbook safety

Every runbook must:

- require a frozen committed execution head and clean tracked tree;
- use absolute paths, plain existing parents and fresh absent output roots;
- reject symlink/reparse components and insufficient disk;
- verify exact profiles and tokenizer assets;
- distinguish live capture (approved intranet access required) from offline
  processing/export (sockets forbidden);
- keep credentials in the process environment only;
- count real invocations and contain no automatic retry;
- preserve valid artifacts after failure;
- emit aggregate-only sanitized evidence;
- never record IDs, paths, hostnames, URLs, content, principals, credentials or
  full hashes;
- never rewrite context/evidence merely to satisfy a head gate;
- never patch production code during a controlled run.

A failed preflight before invocation reports invocation count zero and does not
consume authorization. Once the authorized invocation begins, authorization is
consumed regardless of outcome.

## 6. Required offline preflight

Set:

```text
PYTHONUTF8=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Run at least:

```text
tests/foundation/cli/test_w4_c2_composition.py
tests/foundation/cli/test_confluence_subtree_cli.py
tests/foundation/cli/test_export_m10_snapshot_cli.py
tests/foundation/cli/test_m10_operator_cli_e2e.py
tests/foundation/application/use_cases/test_capture_delta_inventory.py
tests/foundation/application/use_cases/test_project_m10_delta.py
tests/foundation/application/use_cases/test_export_m10_snapshot.py
tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py
tests/foundation/domain/rules/test_snapshot_readback.py
tests/architecture
```

Run exact asset-backed tests with the explicit bundle. They must fail rather
than silently skip when it is missing. Also run `compileall`, `git diff
--check`, and report tracked status.

## 7. Review and stop rules

Use one consolidated fresh independent review after W5-D. The reviewer must not
have implemented, fixed or operated W5 and must not edit files. Review the full
W5-A-through-D code/runbook/evidence range and report P0-P3, exact
commands/results, provenance, boundary confirmation and rerun decisions.

Stage transitions do not require separate independent reviewers, but the live
W5-B and W5-C invocations still require distinct explicit owner authorizations.
The agent must stop at each live-authorization boundary and cannot treat this
prompt as standing permission to invoke Confluence.

Stop if transfer equivalence, clean execution provenance, profiles/assets,
safe real evidence cases, fresh paths, live authorization or sanitization
cannot be proven. Do not guess.

Start with W5-A. Return its inspection/runbook notice and explicitly confirm no
live request. After the owner separately authorizes W5-B and later W5-C, the
same implementation/operator agent may complete A through D. Stop after the
W5-D closeout candidate for one consolidated independent review by Codex.
