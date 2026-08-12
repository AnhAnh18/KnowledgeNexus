[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OperatorConfig,

    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:FailureStage = "preflight"
$script:LiveInvocationCount = 0
$script:EvidenceDirectory = $null
$script:ProfileVerified = $false
$script:TokenizerVerified = $false

function Fail-Gate([string]$Stage) {
    $script:FailureStage = $Stage
    throw [System.InvalidOperationException]::new("W5 gate failed")
}

function Full-Path([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.IndexOf([char]0) -ge 0) {
        Fail-Gate "configuration"
    }
    try {
        return [System.IO.Path]::GetFullPath($Value)
    }
    catch {
        Fail-Gate "configuration"
    }
}

function Assert-PlainExistingPath([string]$Path, [bool]$Directory) {
    $resolved = Full-Path $Path
    if (-not (Test-Path -LiteralPath $resolved)) { Fail-Gate "path_preflight" }
    $cursor = Get-Item -LiteralPath $resolved -Force
    if ($Directory -and -not $cursor.PSIsContainer) { Fail-Gate "path_preflight" }
    if (-not $Directory -and $cursor.PSIsContainer) { Fail-Gate "path_preflight" }
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            Fail-Gate "path_preflight"
        }
        if ($cursor -is [System.IO.FileInfo]) { $cursor = $cursor.Directory }
        else { $cursor = $cursor.Parent }
    }
    return $resolved
}

function Is-Within([string]$Parent, [string]$Candidate) {
    $root = (Full-Path $Parent).TrimEnd('\', '/')
    $path = (Full-Path $Candidate).TrimEnd('\', '/')
    return $path.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $path.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-FreshExternalDirectory([string]$Path, [string]$RepoRoot) {
    $target = Full-Path $Path
    if (Test-Path -LiteralPath $target) { Fail-Gate "fresh_path_preflight" }
    if (Is-Within $RepoRoot $target) { Fail-Gate "fresh_path_preflight" }
    $parent = Split-Path -Parent $target
    [void](Assert-PlainExistingPath $parent $true)
    return $target
}

function Assert-EmptyPlainDirectory([string]$Path) {
    [void](Assert-PlainExistingPath $Path $true)
    if (@(Get-ChildItem -LiteralPath $Path -Force).Count -ne 0) {
        Fail-Gate "fresh_directory_verification"
    }
}

function Quote-ProcessArgument([string]$Value) {
    if ($Value.IndexOf([char]0) -ge 0 -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        Fail-Gate "configuration"
    }
    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (2 * $slashes + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * (2 * $slashes))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-PythonProcess {
    param(
        [string[]]$Arguments,
        [bool]$Live,
        [string]$Stage,
        [bool]$ExpectJson
    )
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $script:PythonExecutable
    $info.WorkingDirectory = $script:RepoRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.Arguments = (($Arguments | ForEach-Object { Quote-ProcessArgument ([string]$_) }) -join ' ')
    $info.EnvironmentVariables["PYTHONPATH"] = Join-Path $script:RepoRoot "src"
    $info.EnvironmentVariables["PYTHONUTF8"] = "1"
    $info.EnvironmentVariables["HF_HUB_OFFLINE"] = "1"
    $info.EnvironmentVariables["TRANSFORMERS_OFFLINE"] = "1"
    if (-not $Live) {
        foreach ($name in @(
            "CONFLUENCE_PAT", "CONFLUENCE_BASE_URL", "HTTP_PROXY", "HTTPS_PROXY",
            "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"
        )) {
            [void]$info.EnvironmentVariables.Remove($name)
        }
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { Fail-Gate $Stage }
        if ($Live) { $script:LiveInvocationCount += 1 }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result
        if ($process.ExitCode -ne 0 -or -not [string]::IsNullOrWhiteSpace($stderr)) {
            Fail-Gate $Stage
        }
        if (-not $ExpectJson) { return $null }
        $lines = @($stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($lines.Count -ne 1) { Fail-Gate $Stage }
        try { return $lines[0] | ConvertFrom-Json }
        catch { Fail-Gate $Stage }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-ModuleJson([string]$Module, [string[]]$Arguments, [bool]$Live, [string]$Stage) {
    return Invoke-PythonProcess -Arguments (@("-m", $Module) + $Arguments) -Live $Live -Stage $Stage -ExpectJson $true
}

function Get-TreeDigest([string[]]$Roots) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $rootIndex = 0
        foreach ($root in ($Roots | Sort-Object)) {
            $rootMarker = [System.Text.Encoding]::UTF8.GetBytes("root-$rootIndex`0")
            [void]$sha.TransformBlock($rootMarker, 0, $rootMarker.Length, $rootMarker, 0)
            $rootIndex += 1
            $entries = @(Get-ChildItem -LiteralPath $root -Recurse -Force)
            if (@($entries | Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -ne 0) {
                Fail-Gate "raw_state_path_safety"
            }
            foreach ($file in @($entries | Where-Object { -not $_.PSIsContainer } | Sort-Object FullName)) {
                $relative = $file.FullName.Substring($root.TrimEnd('\', '/').Length).TrimStart('\', '/')
                $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($relative + "`0")
                [void]$sha.TransformBlock($nameBytes, 0, $nameBytes.Length, $nameBytes, 0)
                $stream = [System.IO.File]::OpenRead($file.FullName)
                try {
                    $buffer = [byte[]]::new(1048576)
                    while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        [void]$sha.TransformBlock($buffer, 0, $read, $buffer, 0)
                    }
                }
                finally { $stream.Dispose() }
            }
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        return ([System.BitConverter]::ToString($sha.Hash)).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Inspect-Snapshot([string]$DatasetRoot, [object]$ExportResult) {
    $rootItems = @(Get-ChildItem -LiteralPath $DatasetRoot -Force)
    $latest = Join-Path $DatasetRoot "LATEST.txt"
    [void](Assert-PlainExistingPath $latest $false)
    $version = [System.IO.File]::ReadAllText($latest, [System.Text.Encoding]::UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($version) -or $version.Contains('/') -or $version.Contains('\')) {
        Fail-Gate "snapshot_readback"
    }
    $versionPath = Join-Path $DatasetRoot $version
    [void](Assert-PlainExistingPath $versionPath $true)
    if ($rootItems.Count -ne 2) { Fail-Gate "snapshot_readback" }
    $expected = @(
        "acl.jsonl", "chunks.jsonl", "documents.jsonl", "manifest.json",
        "media_assets.jsonl", "quality_report.md", "relations.jsonl",
        "symbols.jsonl", "sync_state.jsonl", "tombstones.jsonl"
    ) | Sort-Object
    $observed = @(Get-ChildItem -LiteralPath $versionPath -File -Force | ForEach-Object Name | Sort-Object)
    if (($expected -join "`n") -ne ($observed -join "`n")) { Fail-Gate "snapshot_readback" }
    if (@(Get-ChildItem -LiteralPath $DatasetRoot -Force -Directory | Where-Object { $_.Name.StartsWith(".staging-") }).Count -ne 0) {
        Fail-Gate "snapshot_readback"
    }
    $manifest = Get-Content -LiteralPath (Join-Path $versionPath "manifest.json") -Raw | ConvertFrom-Json
    foreach ($name in @("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")) {
        if ([int64]$manifest.counts.$name -ne [int64]$ExportResult.counts.$name) {
            Fail-Gate "snapshot_readback"
        }
    }
    $hashes = [ordered]@{}
    foreach ($name in $expected) {
        $hashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $versionPath $name)).Hash.ToLowerInvariant()
    }
    $hashes["LATEST.txt"] = (Get-FileHash -Algorithm SHA256 -LiteralPath $latest).Hash.ToLowerInvariant()
    return [pscustomobject]@{ Version = $version; Hashes = $hashes }
}

function Write-SanitizedSummary([bool]$Succeeded, [object]$Counts) {
    if ($null -eq $script:EvidenceDirectory -or -not (Test-Path -LiteralPath $script:EvidenceDirectory)) { return }
    $streamCounts = [ordered]@{
        documents = 0; chunks = 0; relations = 0; acl = 0; media_assets = 0
        sync_state = 0; tombstones = 0; symbols = 0
    }
    if ($null -ne $Counts) {
        foreach ($key in @($streamCounts.Keys)) { $streamCounts[$key] = [int64]$Counts.$key }
    }
    $summary = [ordered]@{
        schema = "w5-b-sanitized-v1"
        authorization_consumed = ($script:LiveInvocationCount -gt 0)
        transfer_equivalent = [bool]$script:Config.transfer_equivalent
        invocation_count = $script:LiveInvocationCount
        controlled_stop_resume = $Succeeded
        committed_work_not_refetched = $Succeeded
        drawio_only = $true
        tokenizer_verified = $script:TokenizerVerified
        profile_verified = $script:ProfileVerified
        publish_repeat_deterministic = $Succeeded
        version_tree_identical = $Succeeded
        raw_state_unchanged = $Succeeded
        strict_readback = $Succeeded
        cross_stream_closed = $Succeeded
        atomic_publication = $Succeeded
        staging_residue_absent = $Succeeded
        stream_counts = $streamCounts
        status = $(if ($Succeeded) { "complete" } else { "failed" })
        failure_category = $(if ($Succeeded) { $null } else { $script:FailureStage })
    }
    $target = Join-Path $script:EvidenceDirectory "w5-b-sanitized-summary.json"
    if (Test-Path -LiteralPath $target) { return }
    $json = $summary | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($target, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

try {
    $configPath = Assert-PlainExistingPath (Full-Path $OperatorConfig) $false
    $configText = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::UTF8)
    try { $script:Config = $configText | ConvertFrom-Json }
    catch { Fail-Gate "configuration" }
    $requiredFields = @(
        "format_version", "owner_authorized", "transfer_equivalent", "expected_execution_head",
        "repo_root", "python_executable", "state_dir", "max_pages", "raw_root",
        "reliability_profile_path", "chunking_profile_path", "jira_relation_profile_path",
        "tokenizer_assets_dir", "space_key", "root_page_id", "dataset_root_a",
        "dataset_root_b", "evidence_dir", "git_repository", "git_branch", "git_commit"
    ) | Sort-Object
    $observedFields = @($script:Config.PSObject.Properties.Name | Sort-Object)
    if (($requiredFields -join "`n") -ne ($observedFields -join "`n")) { Fail-Gate "configuration" }
    if ($script:Config.format_version -ne "w5-b-root1-one-shot-v1" -or
        ((-not $PreflightOnly) -and $script:Config.owner_authorized -ne $true) -or
        $script:Config.transfer_equivalent -ne $true) {
        Fail-Gate "authorization"
    }

    $script:RepoRoot = Assert-PlainExistingPath (Full-Path $script:Config.repo_root) $true
    if (Is-Within $script:RepoRoot $configPath) { Fail-Gate "configuration" }
    $script:PythonExecutable = Assert-PlainExistingPath (Full-Path $script:Config.python_executable) $false
    $head = (& git -C $script:RepoRoot rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$' -or $head -ne $script:Config.expected_execution_head) {
        Fail-Gate "execution_head"
    }
    & git -C $script:RepoRoot diff --quiet
    if ($LASTEXITCODE -ne 0) { Fail-Gate "tracked_worktree" }
    & git -C $script:RepoRoot diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { Fail-Gate "tracked_worktree" }

    if ($script:Config.max_pages -isnot [int64] -and $script:Config.max_pages -isnot [int32]) { Fail-Gate "configuration" }
    $maxPages = [int]$script:Config.max_pages
    if ($maxPages -lt 201 -or $maxPages -gt 5000) { Fail-Gate "page_bound" }
    if ([string]$script:Config.root_page_id -notmatch '^[0-9]+$' -or [string]$script:Config.space_key -notmatch '^[A-Z0-9]+$') {
        Fail-Gate "scope"
    }
    if ([string]$script:Config.git_commit -notmatch '^[0-9a-fA-F]{40}$') { Fail-Gate "configuration" }

    $approvedReliability = Join-Path $script:RepoRoot "contracts/foundation/crawl_reliability_profile.yaml"
    $approvedChunking = Join-Path $script:RepoRoot "contracts/foundation/embedding_profile.yaml"
    $approvedJira = Join-Path $script:RepoRoot "contracts/foundation/jira_relation_profile.yaml"
    $reliability = Assert-PlainExistingPath (Full-Path $script:Config.reliability_profile_path) $false
    $chunking = Assert-PlainExistingPath (Full-Path $script:Config.chunking_profile_path) $false
    $jira = Assert-PlainExistingPath (Full-Path $script:Config.jira_relation_profile_path) $false
    if ($reliability -ne (Full-Path $approvedReliability) -or $chunking -ne (Full-Path $approvedChunking) -or $jira -ne (Full-Path $approvedJira)) {
        Fail-Gate "profile_binding"
    }
    $profileText = [System.IO.File]::ReadAllText($reliability)
    if ($profileText -notmatch '(?m)^minimum_request_interval_seconds:\s*3\.0\s*$' -or
        $profileText -notmatch '(?m)^max_total_requests_per_run:\s*50000\s*$') {
        Fail-Gate "rate_profile"
    }
    $reserveMatch = [regex]::Match($profileText, '(?m)^minimum_free_disk_reserve_bytes:\s*([0-9]+)\s*$')
    if (-not $reserveMatch.Success) { Fail-Gate "profile_binding" }
    $minimumFree = [int64]$reserveMatch.Groups[1].Value
    $tokenizer = Assert-PlainExistingPath (Full-Path $script:Config.tokenizer_assets_dir) $true
    if (Is-Within $script:RepoRoot $tokenizer) { Fail-Gate "tokenizer_boundary" }

    $runtimeTargets = @(
        (Assert-FreshExternalDirectory $script:Config.state_dir $script:RepoRoot),
        (Assert-FreshExternalDirectory $script:Config.raw_root $script:RepoRoot),
        (Assert-FreshExternalDirectory $script:Config.dataset_root_a $script:RepoRoot),
        (Assert-FreshExternalDirectory $script:Config.dataset_root_b $script:RepoRoot),
        (Assert-FreshExternalDirectory $script:Config.evidence_dir $script:RepoRoot)
    )
    if (@($runtimeTargets | Sort-Object -Unique).Count -ne 5) { Fail-Gate "fresh_path_preflight" }
    foreach ($target in $runtimeTargets) {
        $drive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($target))
        if (-not $drive.IsReady -or $drive.AvailableFreeSpace -lt $minimumFree) { Fail-Gate "disk_budget" }
    }

    $testArguments = @(
        "-m", "pytest",
        "tests/foundation/application/use_cases/test_confluence_subtree_capture_resume.py",
        "tests/foundation/cli/test_confluence_subtree_cli.py",
        "tests/foundation/integration/test_w5_a_runbook_artifacts.py",
        "tests/foundation/application/use_cases/test_evaluate_foundation_gates.py",
        "tests/foundation/cli/test_evaluate_foundation_gates_cli.py",
        "tests/foundation/domain/models/test_foundation_gate.py",
        "tests/foundation/infrastructure/config/test_bge_m3_tokenizer_assets.py",
        "tests/foundation/infrastructure/tokenization/test_bge_m3_local_tokenizer.py",
        "tests/architecture", "--tokenizer-assets-dir", $tokenizer, "-q"
    )
    [void](Invoke-PythonProcess -Arguments $testArguments -Live $false -Stage "offline_preflight_tests" -ExpectJson $false)
    [void](Invoke-PythonProcess -Arguments @("-m", "compileall", "-q", "src", "tests") -Live $false -Stage "compileall" -ExpectJson $false)
    $script:ProfileVerified = $true
    $script:TokenizerVerified = $true

    if ($PreflightOnly) {
        [Console]::Out.WriteLine('{"all_gates_passed":true,"authorization_consumed":false,"status":"preflight_complete"}')
        exit 0
    }

    foreach ($target in $runtimeTargets) { [void](New-Item -ItemType Directory -Path $target) }
    foreach ($target in $runtimeTargets) { Assert-EmptyPlainDirectory $target }
    $stateDir, $rawRoot, $datasetA, $datasetB, $script:EvidenceDirectory = $runtimeTargets

    if ([string]::IsNullOrWhiteSpace($env:CONFLUENCE_BASE_URL) -or [string]::IsNullOrWhiteSpace($env:CONFLUENCE_PAT)) {
        Fail-Gate "live_credentials"
    }
    $common = @(
        "--state-dir", $stateDir, "--max-pages", [string]$maxPages,
        "--raw-root", $rawRoot, "--reliability-profile-path", $reliability,
        "--chunking-profile-path", $chunking, "--tokenizer-assets-dir", $tokenizer,
        "--space-key", [string]$script:Config.space_key,
        "--root-page-id", [string]$script:Config.root_page_id
    )

    $inventoryStarted = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("inventory") + $common) $true "inventory_start"
    $inventory = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("inventory") + $common + @("--resume-unique")) $true "inventory_readback"
    if ($inventory.status -ne "complete" -or [string]::IsNullOrWhiteSpace([string]$inventory.run_id) -or
        [int]$inventory.selected_pages -lt 201 -or [int]$inventory.selected_pages -gt $maxPages) {
        Fail-Gate "inventory_readback"
    }
    $runId = [string]$inventory.run_id

    $stopped = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-pages") + $common + @("--run-id", $runId, "--stop-after-batches", "2")) $true "controlled_stop"
    if ($stopped.status -ne "stopped" -or [int]$stopped.captured -ne 200 -or [int]$stopped.replayed -ne 0 -or [int]$stopped.failed -ne 0) {
        Fail-Gate "controlled_stop"
    }
    $resumed = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-pages") + $common + @("--run-id", $runId)) $true "capture_resume"
    if ($resumed.status -ne "complete" -or [int]$resumed.replayed -ne 200 -or [int]$resumed.failed -ne 0) {
        Fail-Gate "capture_resume"
    }

    $processed = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("process-pages") + $common + @("--run-id", $runId)) $false "process_pages"
    if ($processed.status -ne "complete" -or [int]$processed.page_count -ne [int]$inventory.selected_pages) { Fail-Gate "process_pages" }
    $drawio = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-drawio") + $common + @("--run-id", $runId)) $true "capture_drawio"
    if ($drawio.status -ne "complete" -or [int]$drawio.drawio_references_observed -ne [int]$drawio.drawio_references_resolved) {
        Fail-Gate "capture_drawio"
    }

    Remove-Item Env:CONFLUENCE_PAT -ErrorAction SilentlyContinue
    Remove-Item Env:CONFLUENCE_BASE_URL -ErrorAction SilentlyContinue
    $selection = Join-Path $stateDir "runs/$runId/inventory-selection.json"
    $processing = Join-Path $stateDir "runs/$runId/processing-state.json"
    $drawioState = Join-Path $stateDir "runs/$runId/drawio-state.json"
    foreach ($file in @($selection, $processing, $drawioState)) { [void](Assert-PlainExistingPath $file $false) }
    $generatedAt = [System.DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ", [System.Globalization.CultureInfo]::InvariantCulture)
    $rawStateBefore = Get-TreeDigest @($rawRoot, $stateDir)

    function Export-Once([string]$DatasetRoot, [string]$Stage) {
        $arguments = @(
            "--export-mode", "full_snapshot", "--raw-generation-root", $rawRoot,
            "--run-id", $runId, "--generation-id", $runId,
            "--chunking-profile", $chunking, "--tokenizer-assets-dir", $tokenizer,
            "--jira-relation-profile", $jira, "--dataset-root", $DatasetRoot,
            "--selection-path", $selection, "--state-dir", $stateDir,
            "--processing-state", $processing, "--drawio-state", $drawioState,
            "--space-key", [string]$script:Config.space_key,
            "--root-page-id", [string]$script:Config.root_page_id,
            "--media-policy", "required", "--git-repository", [string]$script:Config.git_repository,
            "--git-branch", [string]$script:Config.git_branch,
            "--git-commit", [string]$script:Config.git_commit,
            "--generated-at", $generatedAt
        )
        $result = Invoke-ModuleJson "knowledgenexus.foundation.cli.export_m10_snapshot" $arguments $false $Stage
        if ($result.status -ne "success" -or $result.network_used -ne $false -or $result.credentials_used -ne $false) {
            Fail-Gate $Stage
        }
        return $result
    }

    $exportA = Export-Once $datasetA "export_a"
    $viewA = Inspect-Snapshot $datasetA $exportA
    $exportB = Export-Once $datasetB "export_b"
    $viewB = Inspect-Snapshot $datasetB $exportB
    if ($viewA.Version -ne $viewB.Version -or
        (($viewA.Hashes | ConvertTo-Json -Compress) -ne ($viewB.Hashes | ConvertTo-Json -Compress))) {
        Fail-Gate "deterministic_export"
    }
    $rawStateAfter = Get-TreeDigest @($rawRoot, $stateDir)
    if ($rawStateBefore -ne $rawStateAfter) { Fail-Gate "raw_state_mutation" }

    Write-SanitizedSummary $true $exportA.counts
    [Console]::Out.WriteLine('{"all_gates_passed":true,"evidence_written":true,"status":"complete"}')
    exit 0
}
catch {
    try { Write-SanitizedSummary $false $null }
    catch { }
    $payload = [ordered]@{
        all_gates_passed = $false
        authorization_consumed = ($script:LiveInvocationCount -gt 0)
        failure_category = $script:FailureStage
        status = "failed"
    } | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($payload)
    exit 1
}
