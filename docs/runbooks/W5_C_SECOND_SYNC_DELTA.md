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
 $inventory = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus inventory @common | ConvertFrom-Json
 $run = $inventory.run_id
 if (-not $run) { throw "inventory did not return a run identity" }
# COMMAND 1: start page capture. The operator must interrupt this process with
# Ctrl+C only after a committed batch. Do not rerun COMMAND 1 after stopping.
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run
# COMMAND 2: run exactly once after COMMAND 1 was interrupted. It resumes the
# same run and raw root; do not execute it if COMMAND 1 completed normally.
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run
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
