# W5-C - controlled second-sync sparse delta packet

Main-machine operator packet. Execute only after the owner has inspected and
accepted the sanitized W5-B packet and grants a new authorization. This packet
must bind to the accepted W5-B base dataset version without exposing it in
chat or Git.

## Required safe scenario

The owner or authorized administrator must attest a safe, reversible scenario
containing, where available, one content change, one approved 404 case, one
403 access-revoked case, one moved-out-of-scope case, and one ACL-only change.
If any case cannot be established safely, stop and return a pending gate. Never
edit or delete Confluence content from this runbook and never fabricate a
disposition.

Credentials remain only in the live process environment and are cleared before
offline delta export. Never return credentials or raw runtime artifacts.
The delta dataset root must already exist as an empty plain directory outside
the repository; its generated version/staging directories and `LATEST.txt`
must be absent before publication.

## Authorized sequence

The frozen subtree CLI uses a positional phase and requires `--state-dir` and
`--max-pages` for every phase. Fill these placeholders privately on the main
machine; do not copy the resulting command or values into Git.

```powershell
$common = @(
  "--state-dir", "<ABS-STATE-DIR>", "--max-pages", "<MAX-PAGES>",
  "--raw-root", "<ABS-SECOND-RAW-ROOT>",
  "--reliability-profile-path", "<ABS-RELIABILITY-PROFILE>",
  "--chunking-profile-path", "<ABS-CHUNKING-PROFILE>",
  "--tokenizer-assets-dir", "<ABS-BGE-M3-DIR>",
  "--space-key", "<SPACE-KEY>",
  "--root-page-id", "<ROOT-PAGE-ID>"
)
# The first call durably completes inventory work. The second call reads the
# unique completed run and publishes its bound selection. Neither is a page
# body capture invocation.
$inventoryStarted = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus inventory @common | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "inventory start failed" }
$inventory = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus inventory @common `
  --resume-unique | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $inventory.status -ne "complete") {
  throw "inventory completion readback failed"
}
$run = $inventory.run_id
if (-not $run) { throw "inventory did not return a run identity" }
# COMMAND 1: stop cleanly after two committed 100-page batches. The command
# must return exit 0 with semantic status "stopped"; do not use Ctrl+C.
$stopped = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run --stop-after-batches 2 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $stopped.status -ne "stopped") {
  throw "controlled page-capture stop did not complete"
}
# COMMAND 2: resume the same durable run and raw root without a stop limit.
# It must return exit 0 with semantic status "complete" and must not refetch
# pages already committed by COMMAND 1.
$resumed = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $resumed.status -ne "complete") {
  throw "resumed page capture did not complete"
}
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus process-pages @common `
  --run-id $run
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-drawio @common `
  --run-id $run
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-delta-inventory @common `
  --run-id $run --dataset-root "<ABS-BASE-DATASET-ROOT>" `
  --base-dataset-version "<ACCEPTED-BASE-VERSION>"
python -m knowledgenexus.foundation.cli.export_m10_snapshot `
  --export-mode delta --base-dataset-version "<ACCEPTED-BASE-VERSION>" `
  --raw-generation-root "<ABS-SECOND-RAW-ROOT>" `
  --run-id $run --generation-id $run `
  --chunking-profile "<ABS-CHUNKING-PROFILE>" --tokenizer-assets-dir "<ABS-BGE-M3-DIR>" `
  --jira-relation-profile "<ABS-JIRA-RELATION-PROFILE>" `
  --dataset-root "<ABS-DELTA-DATASET-ROOT>" --selection-path "<ABS-SECOND-SELECTION>" `
  --state-dir "<ABS-STATE-DIR>" --processing-state "<ABS-SECOND-PROCESSING-STATE>" `
  --drawio-state "<ABS-SECOND-DRAWIO-STATE>" --space-key "<SPACE-KEY>" `
  --root-page-id "<ROOT-PAGE-ID>" --media-policy required `
  --git-repository "<PINNED-GIT-NAME>" --git-branch "<PINNED-GIT-BRANCH>" `
  --git-commit "<PINNED-GIT-COMMIT>" --generated-at "<RFC3339>" `
  --profile-identity "<PROFILE-IDENTITY>"
```

Complete inventory must precede missing-page probes. Preserve status/body
evidence before checkpointing `delta-inventory.json`. Offline delta export
must run with sockets forbidden and must perform zero GETs.

## Required assertions

Verify sparse rows/tombstones, strict base-overlay readback, exact 404 detail,
403 access revocation, 401/retry failure, in-scope missing inconsistency,
chunk/media/relation/ACL cascade, ACL-only behavior, unchanged empty delta,
deterministic repeat, and unchanged base/raw/state inputs. Return aggregate
results only using `W5_C_SANITIZED_EVIDENCE_TEMPLATE.json`.
