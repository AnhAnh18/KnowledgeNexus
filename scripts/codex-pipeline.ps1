[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Plan')]
    [string]$PlanPath,

    [Parameter(Mandatory, ParameterSetName = 'Task')]
    [string]$Task,

    [ValidateRange(1, 3)]
    [int]$MaxFixCycles = 2
)

$ErrorActionPreference = 'Stop'

function Get-CodexCommand {
    $npmPrefix = npm prefix -g
    $npmCodex = Join-Path $npmPrefix 'codex.cmd'
    if (Test-Path -LiteralPath $npmCodex) {
        return $npmCodex
    }

    return (Get-Command codex -ErrorAction Stop).Source
}

function Invoke-CodexStage {
    param(
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string]$OutputPath
    )

    Write-Host "`n==> $Profile"
    & $script:CodexCommand exec --profile $Profile --output-last-message $OutputPath $Prompt
    if ($LASTEXITCODE -ne 0) {
        throw "Codex stage '$Profile' failed with exit code $LASTEXITCODE."
    }
}

function Assert-CleanWorkingTree {
    param(
        [Parameter(Mandatory)][string]$Stage
    )

    $status = git status --porcelain=v1 --untracked-files=all
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the working tree before $Stage."
    }

    if ($status) {
        throw "Working tree must be clean before $Stage. Commit, stash, or remove unrelated changes before running the pipeline."
    }
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw 'Run this script inside a Git repository.'
}

Assert-CleanWorkingTree -Stage 'starting the workflow'

$runRoot = Join-Path $repoRoot '.codex-workflow'
$runId = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runPath = Join-Path $runRoot $runId
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runPath -ErrorAction Stop | Out-Null
$script:CodexCommand = Get-CodexCommand

$inputPlan = Join-Path $runPath 'PLAN.input.md'
if ($PSCmdlet.ParameterSetName -eq 'Plan') {
    Copy-Item -LiteralPath (Resolve-Path -LiteralPath $PlanPath).Path -Destination $inputPlan
} else {
    "# Task`n`n$Task" | Set-Content -LiteralPath $inputPlan -Encoding utf8
}

$planReview = Join-Path $runPath '01-plan-review.md'
Invoke-CodexStage -Profile 'review' -OutputPath $planReview -Prompt @"
Act as an independent plan critic. Read '$inputPlan' and repository context.
Do not edit files. Identify missing requirements, risks, contradictions,
alternatives, acceptance criteria, and tests. Then provide a rewritten plan.
Start your final response exactly with one line:
RECOMMENDED_IMPLEMENTATION_PROFILE: build
or
RECOMMENDED_IMPLEMENTATION_PROFILE: complex
Choose build only when implementation is fully specified and routine.
"@

$reviewText = Get-Content -LiteralPath $planReview -Raw
$implementationProfile = if ($reviewText -match '(?im)^RECOMMENDED_IMPLEMENTATION_PROFILE:\s*(build|complex)\s*$') {
    $Matches[1].ToLowerInvariant()
} else {
    'complex'
}

$revisedPlan = Join-Path $runPath '02-plan-revised.md'
Invoke-CodexStage -Profile 'complex' -OutputPath (Join-Path $runPath '02-plan-revision-report.md') -Prompt @"
Read '$inputPlan' and independent review '$planReview'. Write the complete,
executable revised plan to '$revisedPlan'. Preserve scope unless the review
establishes a necessary correction. Include acceptance criteria and validation
commands. Do not implement code yet.
"@
if (-not (Test-Path -LiteralPath $revisedPlan)) {
    throw "Plan revision did not create '$revisedPlan'."
}
Assert-CleanWorkingTree -Stage 'starting implementation'

$implementationReport = Join-Path $runPath '03-implementation.md'
Invoke-CodexStage -Profile $implementationProfile -OutputPath $implementationReport -Prompt @"
Implement '$revisedPlan' in this repository. Read relevant code before editing.
Make the smallest complete change, run the plan's validation, and report changed
files, commands, results, and residual risks. Do not change files outside scope.
"@

$fixCycle = 0
do {
    $reviewRound = $fixCycle + 1
    $reviewOutput = Join-Path $runPath ("04-review-{0}.md" -f $reviewRound)
    Invoke-CodexStage -Profile 'review' -OutputPath $reviewOutput -Prompt @"
Perform an independent review of the current uncommitted diff against
'$revisedPlan'. Do not edit files. Report only concrete correctness, security,
behavior-regression, or missing-test findings, ordered P0 through P3. Include
file references and why each finding is real. If none exist, state VERDICT: PASS.
"@

    $findings = Get-Content -LiteralPath $reviewOutput -Raw
    if ($findings -match '(?im)^VERDICT:\s*PASS\s*$') {
        break
    }

    if ($fixCycle -ge $MaxFixCycles) {
        throw "Final review '$reviewOutput' did not report VERDICT: PASS after $MaxFixCycles fix cycle(s). Resolve its findings before rerunning the pipeline."
    }

    $fixCycle++
    $fixProfile = if ($findings -match '(?im)^\s*(?:[-*]\s*)?P[01]\b') { 'complex' } else { 'build' }
    Invoke-CodexStage -Profile $fixProfile -OutputPath (Join-Path $runPath ("05-fix-{0}.md" -f $fixCycle)) -Prompt @"
Read revised plan '$revisedPlan' and independent review '$reviewOutput'. Fix all
confirmed P0-P3 findings in scope. Do not make unrelated changes. Run focused
validation and report each fixed finding, changed file, and test.
"@
} while ($true)

$summary = Join-Path $runPath 'TASK-SUMMARY.md'
Invoke-CodexStage -Profile 'review' -OutputPath $summary -Prompt @"
Create a concise handoff summary using artifacts in '$runPath' and the current
git diff. Include goal, implementation profile, files changed, validation
commands and outcomes, final review verdict, remaining P0-P3 findings or
blockers, and context for the next plan. Do not edit repository files.
"@

Write-Host "`nWorkflow complete. Artifacts: $runPath"
Write-Host "Final handoff: $summary"
