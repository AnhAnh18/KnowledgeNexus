# W5-B - Root-1 controlled full snapshot packet

Main-machine operator packet. Execute only after a distinct owner
authorization naming this one live sequence. Replace angle-bracket values on
the main machine only; never commit or transmit them.

## Required controls

- Freeze and record the approved execution head; require a clean tracked tree.
- Use existing empty plain dataset roots outside the repository; reject
  symlink/reparse components and insufficient free disk. The generated
  version/staging directories and `LATEST.txt` must be absent before publish.
- Keep credentials in the live process environment only and clear them before
  offline processing/export.
- Use the active reliability profile and explicit BGE-M3 tokenizer directory.
- Text plus Draw.io only. Set media policy to `required` only for Draw.io
  references; do not enable generic PDF/image/OCR paths.
- No automatic operator retry. Preserve valid raw/checkpoint artifacts after
  failure and report aggregate counters only.

## Authorized sequence

For the preferred guarded one-command execution, copy
`W5_B_ONE_SHOT_CONFIG.template.json` to an external private directory, replace
its placeholders, set both authorization booleans explicitly, and run in a
fresh PowerShell process:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run-w5-root1-live.ps1 `
  -OperatorConfig "<ABS-PRIVATE-W5-B-CONFIG.json>"
```

The one-shot script performs the sequence below, including the clean stop,
resume, two deterministic exports, strict snapshot inspection, and sanitized
evidence write. Do not dot-source it: the dedicated process intentionally
clears its credential environment after the final live phase. The expanded
commands below remain the normative phase-by-phase reference and recovery aid.
Before authorization, the same private config can be checked without creating
runtime directories or starting a live process by adding `-PreflightOnly`.

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
<ABS-DATASET-ROOT-B>` and the same semantic inputs and `generated_at`. Before
each publish, its dataset root must already exist as an empty plain directory
outside the repository. The generated version directory, its staging sibling,
and `LATEST.txt` must be absent. Verify privately that version directories,
dataset version, digest, eight streams, strict readback, counts, cross-stream
closure, `LATEST.txt`, and raw/state inputs are byte-identical.

## Sanitized return packet

Return only the aggregate fields in `W5_B_SANITIZED_EVIDENCE_TEMPLATE.json`.
Do not return IDs, URLs, hostnames, paths, titles, raw logs, credentials, or
full hashes. Include `authorization_consumed` even when the run fails after its
first live invocation.
