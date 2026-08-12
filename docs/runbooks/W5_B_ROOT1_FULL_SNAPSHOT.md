# W5-B - Root-1 controlled full snapshot packet

Main-machine operator packet. Execute only after a distinct owner
authorization naming this one live sequence. Replace angle-bracket values on
the main machine only; never commit or transmit them.

## Required controls

- Freeze and record the approved execution head; require a clean tracked tree.
- All five configured runtime roots must be absent before the preferred live
  invocation. Their parents must be existing plain external directories. The
  operator creates the roots itself and rejects symlink/reparse components,
  insufficient free disk, or pre-existing publication state.
- Keep credentials in the live process environment only and clear them before
  offline processing/export.
- Use the active reliability profile and explicit BGE-M3 tokenizer directory.
- Text plus Draw.io only. Set media policy to `required` only for Draw.io
  references; do not enable generic PDF/image/OCR paths.
- No automatic operator retry. Preserve valid raw/checkpoint artifacts after
  failure and report aggregate counters only.
- Every child process has a finite time and working-set limit from the private
  config. The raw-page store enforces the active total-byte and disk-reserve
  budgets before each immutable publication.
- The template uses a conservative 4-GiB child working-set ceiling. The owner
  may raise it only within the script's finite 64-GiB ceiling and at least
  2 GiB below detected physical memory; resource exhaustion fails closed and
  is not an authorization to retry.
- The operator waits at least the active three-second interval after one live
  child exits before starting another, preserving the 20-request/minute bound
  across process boundaries.
- Sanitized `invocation_count` counts live CLI child processes, not individual
  HTTP attempts. Durable checkpoint reservation remains the authority for the
  per-run request budget.

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
commands below are a diagnostic phase reference, not authorization to retry.
Before authorization, the same private config can be checked without creating
the configured runtime roots, pytest cache, or Python bytecode, and without
starting a live process by adding `-PreflightOnly`.

If the live process has started, never invoke the preferred command a second
time. If post-run PowerShell/readback fails after publication, run the same
script with `-RecoveryOnly`. Recovery requires the existing five runtime roots,
reads the private export state and both snapshots, makes zero exporter, live,
or network invocations, calls the production strict readback in one
credential-scrubbed Python process, and writes a separate sanitized recovery
summary:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run-w5-root1-live.ps1 `
  -OperatorConfig "<ABS-PRIVATE-W5-B-CONFIG.json>" `
  -RecoveryOnly
```

Recovery fails closed when either publication is incomplete. Retain partial
artifacts for review. A later offline export, if authorized, must use fresh
dataset roots and a fresh `generated_at`; it is not performed by this runbook.
The private export-state file contains the run identity and a full local digest;
it remains external and must never be copied into Git or durable review docs.
If failure occurs during inventory/page/Draw.io capture, retain state and raw
roots unchanged and stop. The preferred one-shot cannot be rerun against those
non-fresh roots. Resume is a separately authorized, phase-specific operator
task using the recorded run and the expanded command shapes below; it must
repeat the three-second cross-process guard and must not refetch committed raw
pages. Empty or partially published dataset roots receive an explicit reviewer
disposition before any later offline publication.

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
Start-Sleep -Seconds 3
$inventory = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus inventory @common `
  --resume-unique | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $inventory.status -ne "complete") {
  throw "inventory completion readback failed"
}
Start-Sleep -Seconds 3
$run = $inventory.run_id
if (-not $run) { throw "inventory did not return a run identity" }
# COMMAND 1: stop cleanly after two committed 100-page batches. The command
# must return exit 0 with semantic status "stopped"; do not use Ctrl+C.
$stopped = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run --stop-after-batches 2 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $stopped.status -ne "stopped") {
  throw "controlled page-capture stop did not complete"
}
Start-Sleep -Seconds 3
# COMMAND 2: resume the same durable run and raw root without a stop limit.
# It must return exit 0 with semantic status "complete" and must not refetch
# pages already committed by COMMAND 1.
$resumed = python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-pages @common `
  --run-id $run | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $resumed.status -ne "complete") {
  throw "resumed page capture did not complete"
}
Start-Sleep -Seconds 3
# Diagnostic argument shape only: the preferred one-shot supplies this array
# to its credential-scrubbed child ProcessStartInfo. Do not invoke it directly
# in this still credential-bearing shell.
$processPagesArguments = @(
  "-m", "knowledgenexus.foundation.cli.confluence_subtree_corpus",
  "process-pages"
) + $common + @("--run-id", $run)
# Even if offline processing completes unusually quickly, preserve the live
# transport boundary before Draw.io metadata/body requests.
Start-Sleep -Seconds 3
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus capture-drawio @common `
  --run-id $run
# Draw.io is the final live phase. Only now clear connector/proxy variables;
# both export commands below are offline children.
Remove-Item Env:CONFLUENCE_PAT -ErrorAction SilentlyContinue
Remove-Item Env:CONFLUENCE_BASE_URL -ErrorAction SilentlyContinue
foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")) {
  Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
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
<ABS-DATASET-ROOT-B>` and the same semantic inputs and `generated_at`. In the
preferred flow the script created each absent dataset root as an empty plain
external directory before any live invocation. The generated version
directory, its staging sibling, and `LATEST.txt` must be absent. Verify
privately that version directories,
dataset version, digest, eight streams, strict readback, counts, cross-stream
closure, `LATEST.txt`, and raw/state inputs are byte-identical.

## Sanitized return packet

Return only the aggregate fields in `W5_B_SANITIZED_EVIDENCE_TEMPLATE.json`.
Do not return IDs, URLs, hostnames, paths, titles, raw logs, credentials, or
full hashes. Include `authorization_consumed` even when the run fails after its
first live invocation.
