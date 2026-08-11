# W5-B - Root-1 controlled full snapshot packet

Main-machine operator packet. Execute only after a distinct owner
authorization naming this one live sequence. Replace angle-bracket values on
the main machine only; never commit or transmit them.

## Required controls

- Freeze and record the approved execution head; require a clean tracked tree.
- Use fresh absent output roots with plain existing parents; reject symlink or
  reparse components and insufficient free disk.
- Keep credentials in the live process environment only and clear them before
  offline processing/export.
- Use the active reliability profile and explicit BGE-M3 tokenizer directory.
- Text plus Draw.io only. Set media policy to `required` only for Draw.io
  references; do not enable generic PDF/image/OCR paths.
- No automatic operator retry. Preserve valid raw/checkpoint artifacts after
  failure and report aggregate counters only.

## Authorized sequence

The frozen subtree CLI uses a positional phase and requires `--state-dir` and
`--max-pages` for every phase. The operator fills the placeholders privately
and keeps the resulting command transcript off-repository.

```powershell
$common = @(
  "--state-dir", "<ABS-STATE-DIR>", "--max-pages", "<MAX-PAGES>",
  "--raw-root", "<ABS-RAW-ROOT>",
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
# Ctrl+C only after its output confirms a committed batch. This is the one
# controlled stop; do not rerun COMMAND 1 after interruption.
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
python -m knowledgenexus.foundation.cli.export_m10_snapshot `
  --export-mode full_snapshot --raw-generation-root "<ABS-RAW-ROOT>" `
  --run-id $run --generation-id $run `
  --chunking-profile "<ABS-CHUNKING-PROFILE>" `
  --tokenizer-assets-dir "<ABS-BGE-M3-DIR>" `
  --jira-relation-profile "<ABS-JIRA-RELATION-PROFILE>" `
  --dataset-root "<ABS-DATASET-ROOT-A>" --selection-path "<ABS-SELECTION>" `
  --state-dir "<ABS-STATE-DIR>" --processing-state "<ABS-PROCESSING-STATE>" `
  --drawio-state "<ABS-DRAWIO-STATE>" --space-key "<SPACE-KEY>" `
  --root-page-id "<ROOT-PAGE-ID>" --media-policy required `
  --git-repository "<PINNED-GIT-NAME>" --git-branch "<PINNED-GIT-BRANCH>" `
  --git-commit "<PINNED-GIT-COMMIT>" --generated-at "<RFC3339>" `
  --profile-identity "<PROFILE-IDENTITY>"
```

Exercise one controlled stop after committed batches, then resume the same run
and prove committed windows/pages were not fetched again. Do not start a second
live sequence after the authorized sequence completes.

Repeat only the offline export command with `--dataset-root
<ABS-DATASET-ROOT-B>` and the same semantic inputs and `generated_at`. Both
dataset roots must be fresh and absent before each publish. Verify privately
that version directories, dataset version, digest, eight streams, strict
readback, counts, cross-stream closure, `LATEST.txt`, and raw/state inputs are
byte-identical.

## Sanitized return packet

Return only the aggregate fields in `W5_B_SANITIZED_EVIDENCE_TEMPLATE.json`.
Do not return IDs, URLs, hostnames, paths, titles, raw logs, credentials, or
full hashes. Include `authorization_consumed` even when the run fails after its
first live invocation.
