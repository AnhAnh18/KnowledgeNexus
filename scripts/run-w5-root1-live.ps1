[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OperatorConfig,

    [switch]$PreflightOnly,

    [switch]$RecoveryOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:FailureStage = "preflight"
$script:LiveInvocationCount = 0
$script:EvidenceDirectory = $null
$script:ProfileVerified = $false
$script:TokenizerVerified = $false
$script:LastLiveProcessCompletedAt = $null
$script:MinimumRequestIntervalSeconds = 3.0
$script:OperatorMode = "live"
$script:SummaryFileName = "w5-b-sanitized-summary.json"
$script:OriginalAuthorizationConsumed = $false
$script:OriginalLiveInvocationCount = 0
$script:ExporterInvocationCount = 0
$script:CaptureFailureCategories = $null
$script:PostInventoryFailureCategories = @(
    "raw_generation_activation_run_operation_invalid",
    "raw_generation_activation_run_not_found",
    "raw_generation_activation_run_not_resumable",
    "raw_generation_activation_run_match_ambiguous",
    "raw_generation_activation_incomplete_run_conflict",
    "inventory_stream",
    "inventory_selection_invalid",
    "selection_publication"
)

function Fail-Gate([string]$Stage) {
    $script:FailureStage = $Stage
    throw [System.InvalidOperationException]::new("W5 gate failed")
}

function Get-StrictTopLevelJsonPropertyNames([string]$Json) {
    # Parse the outer property boundary before ConvertFrom-Json so PowerShell
    # 5.1 cannot silently collapse duplicate keys. Config type checks still
    # require primitive values; nested tracking also lets this guard protect
    # the export child's one nested counts object.
    if ([string]::IsNullOrWhiteSpace($Json)) { Fail-Gate "configuration" }
    $allNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $propertyPattern = '"(?:\\["\\/bfnrt]|\\u[0-9a-fA-F]{4}|[^"\\])*"\s*:'
    $stringPattern = '^("(?:\\["\\/bfnrt]|\\u[0-9a-fA-F]{4}|[^"\\])*")'
    foreach ($match in [regex]::Matches($Json, $propertyPattern)) {
        $token = [regex]::Match($match.Value, $stringPattern).Groups[1].Value
        try { $decoded = $token | ConvertFrom-Json }
        catch { Fail-Gate "configuration" }
        if ($decoded -isnot [string] -or -not $allNames.Add($decoded)) {
            Fail-Gate "configuration"
        }
    }
    $index = 0
    while ($index -lt $Json.Length -and [char]::IsWhiteSpace($Json[$index])) { $index += 1 }
    if ($index -ge $Json.Length -or $Json[$index] -ne '{') { Fail-Gate "configuration" }
    $index += 1
    $names = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    while ($true) {
        while ($index -lt $Json.Length -and [char]::IsWhiteSpace($Json[$index])) { $index += 1 }
        if ($index -lt $Json.Length -and $Json[$index] -eq '}') {
            $index += 1
            break
        }
        if ($index -ge $Json.Length -or $Json[$index] -ne '"') { Fail-Gate "configuration" }
        $index += 1
        $builder = [System.Text.StringBuilder]::new()
        while ($index -lt $Json.Length -and $Json[$index] -ne '"') {
            if ($Json[$index] -eq '\') {
                # Required operator keys are fixed ASCII literals; escaped key
                # aliases are rejected rather than normalized ambiguously.
                Fail-Gate "configuration"
            }
            [void]$builder.Append($Json[$index])
            $index += 1
        }
        if ($index -ge $Json.Length) { Fail-Gate "configuration" }
        $index += 1
        $name = $builder.ToString()
        if ([string]::IsNullOrEmpty($name) -or -not $seen.Add($name)) { Fail-Gate "configuration" }
        [void]$names.Add($name)
        while ($index -lt $Json.Length -and [char]::IsWhiteSpace($Json[$index])) { $index += 1 }
        if ($index -ge $Json.Length -or $Json[$index] -ne ':') { Fail-Gate "configuration" }
        $index += 1
        while ($index -lt $Json.Length -and [char]::IsWhiteSpace($Json[$index])) { $index += 1 }
        $valueStart = $index
        $inString = $false
        $escaped = $false
        $nestedDepth = 0
        while ($index -lt $Json.Length) {
            $character = $Json[$index]
            if ($inString) {
                if ($escaped) { $escaped = $false }
                elseif ($character -eq '\') { $escaped = $true }
                elseif ($character -eq '"') { $inString = $false }
                $index += 1
                continue
            }
            if ($character -eq '"') { $inString = $true; $index += 1; continue }
            if ($character -eq '{' -or $character -eq '[') {
                $nestedDepth += 1
                $index += 1
                continue
            }
            if ($character -eq ']') {
                if ($nestedDepth -le 0) { Fail-Gate "configuration" }
                $nestedDepth -= 1
                $index += 1
                continue
            }
            if ($character -eq '}') {
                if ($nestedDepth -gt 0) {
                    $nestedDepth -= 1
                    $index += 1
                    continue
                }
                break
            }
            if ($character -eq ',' -and $nestedDepth -eq 0) { break }
            $index += 1
        }
        if ($inString -or $nestedDepth -ne 0 -or $index -le $valueStart -or
            [string]::IsNullOrWhiteSpace($Json.Substring($valueStart, $index - $valueStart))) {
            Fail-Gate "configuration"
        }
        if ($index -ge $Json.Length) { Fail-Gate "configuration" }
        if ($Json[$index] -eq ',') {
            $index += 1
            $lookahead = $index
            while ($lookahead -lt $Json.Length -and [char]::IsWhiteSpace($Json[$lookahead])) { $lookahead += 1 }
            if ($lookahead -ge $Json.Length -or $Json[$lookahead] -eq '}') { Fail-Gate "configuration" }
            continue
        }
        $index += 1
        break
    }
    while ($index -lt $Json.Length -and [char]::IsWhiteSpace($Json[$index])) { $index += 1 }
    if ($index -ne $Json.Length) { Fail-Gate "configuration" }
    return $names.ToArray()
}

function Assert-ExactObject([object]$Value, [string[]]$Fields, [string]$Stage) {
    if ($null -eq $Value -or $Value -is [System.Array] -or
        $Value.GetType().FullName -ne "System.Management.Automation.PSCustomObject") {
        Fail-Gate $Stage
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Fields | Sort-Object)
    if (($actual -join "`n") -ne ($expected -join "`n")) { Fail-Gate $Stage }
}

function Assert-ExactString([object]$Value, [string]$Stage, [string]$Pattern = "") {
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value)) { Fail-Gate $Stage }
    if ($Pattern -and $Value -notmatch $Pattern) { Fail-Gate $Stage }
}

function Assert-ExactBoolean([object]$Value, [string]$Stage) {
    if ($Value -isnot [bool]) { Fail-Gate $Stage }
}

function Assert-ExactInteger([object]$Value, [string]$Stage, [int64]$Minimum = 0) {
    if (($Value -isnot [int32] -and $Value -isnot [int64]) -or [int64]$Value -lt $Minimum) {
        Fail-Gate $Stage
    }
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

function Wait-LiveProcessBoundary {
    if ($null -eq $script:LastLiveProcessCompletedAt) { return }
    $frequency = [double][System.Diagnostics.Stopwatch]::Frequency
    $now = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $elapsed = ([double]($now - $script:LastLiveProcessCompletedAt)) / $frequency
    $remaining = $script:MinimumRequestIntervalSeconds - $elapsed
    if ($remaining -gt 0) {
        Start-Sleep -Milliseconds ([int][Math]::Ceiling($remaining * 1000.0))
    }
}

function Assert-PhaseResultEnvelope(
    [object]$Value,
    [string[]]$SuccessFields,
    [string]$Stage
) {
    if ($null -eq $Value -or $Value -is [System.Array] -or
        $Value.GetType().FullName -ne "System.Management.Automation.PSCustomObject") {
        Fail-Gate $Stage
    }
    $actualFields = @($Value.PSObject.Properties.Name | Sort-Object)
    $failureFields = @("failure_category", "status")
    if (($actualFields -join "`n") -eq ($failureFields -join "`n")) {
        Assert-ExactObject $Value @("status", "failure_category") $Stage
        Assert-ExactString $Value.status $Stage
        Assert-ExactString $Value.failure_category $Stage
        if ($Value.status -ne "failed") { Fail-Gate $Stage }
        if ($script:PostInventoryFailureCategories -notcontains $Value.failure_category) {
            Fail-Gate $Stage
        }
        Fail-Gate $Value.failure_category
    }
    Assert-ExactObject $Value $SuccessFields $Stage
}

function Assert-InventoryResult([object]$Value, [string]$Stage) {
    Assert-PhaseResultEnvelope $Value @("status", "phase", "selected_pages", "run_id") $Stage
    Assert-ExactString $Value.status $Stage
    Assert-ExactString $Value.phase $Stage
    Assert-ExactString $Value.run_id $Stage '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    Assert-ExactInteger $Value.selected_pages $Stage 1
    if ($Value.status -ne "complete" -or $Value.phase -ne "inventory") { Fail-Gate $Stage }
}

function Assert-CaptureResult([object]$Value, [string]$ExpectedStatus, [string]$Stage) {
    if ($null -eq $Value -or $Value -is [System.Array] -or
        $Value.GetType().FullName -ne "System.Management.Automation.PSCustomObject") {
        Fail-Gate $Stage
    }
    $baseFields = @("status", "phase", "captured", "replayed", "skipped", "failed") | Sort-Object
    $failureFields = @($baseFields + "failure_categories") | Sort-Object
    $actualFields = @($Value.PSObject.Properties.Name | Sort-Object)
    $hasFailureCategories = (($actualFields -join "`n") -eq ($failureFields -join "`n"))
    $expectedFields = $(if ($hasFailureCategories) { $failureFields } else { $baseFields })
    Assert-PhaseResultEnvelope $Value $expectedFields $Stage
    Assert-ExactString $Value.status $Stage
    Assert-ExactString $Value.phase $Stage
    foreach ($field in @("captured", "replayed", "skipped", "failed")) {
        Assert-ExactInteger $Value.$field $Stage 0
    }
    if ($Value.status -ne $ExpectedStatus -or $Value.phase -ne "capture-pages" -or
        [int64]$Value.skipped -ne 0) { Fail-Gate $Stage }
    if ([int64]$Value.failed -eq 0) {
        if ($hasFailureCategories) { Fail-Gate $Stage }
    } else {
        if (-not $hasFailureCategories -or $null -eq $Value.failure_categories -or
            $Value.failure_categories -is [System.Array] -or
            $Value.failure_categories.GetType().FullName -ne "System.Management.Automation.PSCustomObject") {
            Fail-Gate $Stage
        }
        $allowed = @(
            "acknowledgement_conflict", "acknowledgement_identity_conflict",
            "acknowledgement_inspection_failed", "acknowledgement_invalid",
            "acknowledgement_invalid_request", "acknowledgement_missing",
            "acknowledgement_result_invalid", "acknowledgement_schema_incompatible",
            "acknowledgement_unknown_inventory", "acknowledgement_unsafe_target",
            "fetch_failure_invalid", "fetch_http", "fetch_identity_mismatch",
            "fetch_invalid_page_id", "fetch_invalid_run_id", "fetch_malformed_json",
            "fetch_non_object_json", "fetch_response_size_limit",
            "fetch_source_version_invalid", "fetch_store", "replay_conflict",
            "replay_identity_conflict", "replay_inspection_failed", "replay_invalid",
            "replay_invalid_request", "replay_result_invalid",
            "replay_schema_incompatible", "replay_unknown_inventory",
            "replay_unsafe_target"
        )
        $categoryNames = @($Value.failure_categories.PSObject.Properties.Name | Sort-Object)
        if ($categoryNames.Count -eq 0) { Fail-Gate $Stage }
        $sum = [int64]0
        $sanitized = [ordered]@{}
        foreach ($name in $categoryNames) {
            if ($allowed -notcontains $name) { Fail-Gate $Stage }
            Assert-ExactInteger $Value.failure_categories.$name $Stage 1
            $count = [int64]$Value.failure_categories.$name
            $sum += $count
            $sanitized[$name] = $count
        }
        if ($sum -ne [int64]$Value.failed) { Fail-Gate $Stage }
        $script:CaptureFailureCategories = $sanitized
        Fail-Gate $Stage
    }
    if ($ExpectedStatus -eq "stopped" -and
        ([int64]$Value.captured -ne 200 -or [int64]$Value.replayed -ne 0)) { Fail-Gate $Stage }
    if ($ExpectedStatus -eq "complete" -and [int64]$Value.replayed -ne 200) { Fail-Gate $Stage }
}

function Assert-ProcessingResult([object]$Value, [string]$Stage) {
    Assert-ExactObject $Value @("status", "phase", "page_count", "document_count", "chunk_count") $Stage
    foreach ($field in @("page_count", "document_count", "chunk_count")) {
        Assert-ExactInteger $Value.$field $Stage 0
    }
    if ($Value.status -ne "complete" -or $Value.phase -ne "process-pages" -or
        [int64]$Value.page_count -le 0 -or
        [int64]$Value.document_count -ne [int64]$Value.page_count -or
        [int64]$Value.chunk_count -lt [int64]$Value.document_count) { Fail-Gate $Stage }
}

function Assert-DrawioResult([object]$Value, [string]$Stage) {
    Assert-ExactObject $Value @(
        "status", "phase", "drawio_references_observed",
        "drawio_references_resolved", "drawio_assets_failed"
    ) $Stage
    foreach ($field in @(
        "drawio_references_observed", "drawio_references_resolved", "drawio_assets_failed"
    )) { Assert-ExactInteger $Value.$field $Stage 0 }
    if ($Value.status -ne "complete" -or $Value.phase -ne "capture-drawio" -or
        [int64]$Value.drawio_assets_failed -ne 0 -or
        [int64]$Value.drawio_references_observed -ne [int64]$Value.drawio_references_resolved) {
        Fail-Gate $Stage
    }
}

function Assert-ExportResult([object]$Value, [string]$Stage) {
    Assert-ExactObject $Value @("status", "dataset_version", "counts", "network_used", "credentials_used") $Stage
    Assert-ExactString $Value.status $Stage
    Assert-ExactString $Value.dataset_version $Stage '^v[0-9]{8}-[0-9]{6}-[0-9]{6}Z$'
    Assert-ExactBoolean $Value.network_used $Stage
    Assert-ExactBoolean $Value.credentials_used $Stage
    $countFields = @("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
    Assert-ExactObject $Value.counts $countFields $Stage
    foreach ($field in $countFields) { Assert-ExactInteger $Value.counts.$field $Stage 0 }
    if ($Value.status -ne "success" -or $Value.network_used -ne $false -or $Value.credentials_used -ne $false) {
        Fail-Gate $Stage
    }
    if ([int64]$Value.counts.documents -le 0 -or
        [int64]$Value.counts.chunks -lt [int64]$Value.counts.documents -or
        [int64]$Value.counts.acl -ne [int64]$Value.counts.documents -or
        [int64]$Value.counts.sync_state -ne
            ([int64]$Value.counts.documents + [int64]$Value.counts.media_assets) -or
        [int64]$Value.counts.symbols -ne 0 -or [int64]$Value.counts.tombstones -ne 0) {
        Fail-Gate $Stage
    }
}

function Assert-VerificationResult([object]$Value, [string]$Stage) {
    Assert-ExactObject $Value @(
        "status", "strict_readback", "cross_stream_closed",
        "version_trees_identical", "counts"
    ) $Stage
    foreach ($field in @("strict_readback", "cross_stream_closed", "version_trees_identical")) {
        Assert-ExactBoolean $Value.$field $Stage
        if ($Value.$field -ne $true) { Fail-Gate $Stage }
    }
    $countFields = @("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
    Assert-ExactObject $Value.counts $countFields $Stage
    foreach ($field in $countFields) { Assert-ExactInteger $Value.counts.$field $Stage 0 }
    if ($Value.status -ne "complete") { Fail-Gate $Stage }
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
    $info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1"
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
    $started = $false
    try {
        if ($Live) { Wait-LiveProcessBoundary }
        if (-not $process.Start()) { Fail-Gate $Stage }
        $started = $true
        if ($Live) { $script:LiveInvocationCount += 1 }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $timeout = $(if ($Live) {
            [int64]$script:Config.live_phase_timeout_seconds
        } else {
            [int64]$script:Config.offline_phase_timeout_seconds
        })
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $resourceFailure = $null
        while (-not $process.WaitForExit(100)) {
            try {
                $process.Refresh()
                $workingSet = [int64]$process.WorkingSet64
            }
            catch [System.InvalidOperationException] { continue }
            if ($workingSet -gt [int64]$script:Config.max_child_working_set_bytes -or
                [int64]$process.PeakWorkingSet64 -gt [int64]$script:Config.max_child_working_set_bytes) {
                $resourceFailure = "child_memory_budget"
                break
            }
            if ($stopwatch.Elapsed.TotalSeconds -gt $timeout) {
                $resourceFailure = "child_time_budget"
                break
            }
        }
        if ($null -ne $resourceFailure) {
            try { $process.Kill() } catch { }
            try {
                if (-not $process.WaitForExit(5000)) { Fail-Gate "child_termination" }
            }
            catch { Fail-Gate "child_termination" }
            Fail-Gate $resourceFailure
        }
        $process.Refresh()
        if ($stopwatch.Elapsed.TotalSeconds -gt $timeout) { Fail-Gate "child_time_budget" }
        if ([int64]$process.PeakWorkingSet64 -gt [int64]$script:Config.max_child_working_set_bytes) {
            Fail-Gate "child_memory_budget"
        }
        if (-not $process.WaitForExit(5000) -or
            -not $stdoutTask.Wait(5000) -or -not $stderrTask.Wait(5000)) {
            Fail-Gate "child_termination"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or -not [string]::IsNullOrWhiteSpace($stderr)) {
            Fail-Gate $Stage
        }
        if (-not $ExpectJson) { return $null }
        $lines = @($stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($lines.Count -ne 1) { Fail-Gate $Stage }
        try { [void]@(Get-StrictTopLevelJsonPropertyNames $lines[0]) }
        catch { Fail-Gate $Stage }
        try { return $lines[0] | ConvertFrom-Json }
        catch { Fail-Gate $Stage }
    }
    finally {
        if ($Live -and $started) {
            # Waiting from process completion is conservative: the final HTTP
            # attempt necessarily started before this timestamp.
            $script:LastLiveProcessCompletedAt = [System.Diagnostics.Stopwatch]::GetTimestamp()
        }
        $process.Dispose()
    }
}

function Invoke-ModuleJson([string]$Module, [string[]]$Arguments, [bool]$Live, [string]$Stage) {
    return Invoke-PythonProcess -Arguments (@("-m", $Module) + $Arguments) -Live $Live -Stage $Stage -ExpectJson $true
}

function Invoke-ExporterModuleJson([string[]]$Arguments, [string]$Stage) {
    $script:ExporterInvocationCount += 1
    return Invoke-ModuleJson "knowledgenexus.foundation.cli.export_m10_snapshot" $Arguments $false $Stage
}

function New-FailurePayload([bool]$AuthorizationConsumed) {
    $payload = [ordered]@{
        all_gates_passed = $false
        authorization_consumed = $AuthorizationConsumed
        exporter_invocations = $script:ExporterInvocationCount
        failure_category = $script:FailureStage
        status = "failed"
    }
    if ($null -ne $script:CaptureFailureCategories) {
        $payload["capture_failure_categories"] = $script:CaptureFailureCategories
    }
    return $payload
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

function Write-PrivateExportState([string]$Target, [string]$RunId, [string]$RawStateDigest) {
    if (Test-Path -LiteralPath $Target) { Fail-Gate "private_state" }
    $payload = [ordered]@{
        format_version = "w5-b-private-export-state-v1"
        run_id = $RunId
        raw_state_digest_before_export = $RawStateDigest
        original_live_process_invocations = $script:LiveInvocationCount
        profile_verified = $script:ProfileVerified
        tokenizer_verified = $script:TokenizerVerified
    } | ConvertTo-Json -Compress
    $temporary = Join-Path (Split-Path -Parent $Target) (".w5-private-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [System.IO.File]::WriteAllText($temporary, $payload + "`n", [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Target
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Read-PrivateExportState([string]$Target) {
    [void](Assert-PlainExistingPath $Target $false)
    $text = [System.IO.File]::ReadAllText($Target, [System.Text.Encoding]::UTF8)
    try { $names = @(Get-StrictTopLevelJsonPropertyNames $text | Sort-Object) }
    catch { Fail-Gate "private_state" }
    $expected = @(
        "format_version", "run_id", "raw_state_digest_before_export",
        "original_live_process_invocations", "profile_verified", "tokenizer_verified"
    ) | Sort-Object
    if (($names -join "`n") -ne ($expected -join "`n")) { Fail-Gate "private_state" }
    try { $value = $text | ConvertFrom-Json } catch { Fail-Gate "private_state" }
    Assert-ExactObject $value $expected "private_state"
    Assert-ExactString $value.run_id "private_state" '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    Assert-ExactString $value.raw_state_digest_before_export "private_state" '^[0-9a-f]{64}$'
    Assert-ExactInteger $value.original_live_process_invocations "private_state" 1
    Assert-ExactBoolean $value.profile_verified "private_state"
    Assert-ExactBoolean $value.tokenizer_verified "private_state"
    if ($value.format_version -ne "w5-b-private-export-state-v1" -or
        $value.profile_verified -ne $true -or $value.tokenizer_verified -ne $true) {
        Fail-Gate "private_state"
    }
    return $value
}

function Inspect-Snapshot([string]$DatasetRoot, [object]$ExportResult = $null) {
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
    $countFields = @("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
    Assert-ExactObject $manifest.counts $countFields "snapshot_readback"
    foreach ($name in $countFields) {
        Assert-ExactInteger $manifest.counts.$name "snapshot_readback" 0
        if ($null -ne $ExportResult -and [int64]$manifest.counts.$name -ne [int64]$ExportResult.counts.$name) {
            Fail-Gate "snapshot_readback"
        }
    }
    $hashes = [ordered]@{}
    foreach ($name in $expected) {
        $hashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $versionPath $name)).Hash.ToLowerInvariant()
    }
    $hashes["LATEST.txt"] = (Get-FileHash -Algorithm SHA256 -LiteralPath $latest).Hash.ToLowerInvariant()
    return [pscustomobject]@{ Version = $version; Hashes = $hashes; Counts = $manifest.counts }
}

function Write-SanitizedSummary(
    [bool]$Succeeded,
    [object]$Counts,
    [bool]$AuthorizationConsumed,
    [int]$InvocationCount,
    [string]$FileName
) {
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
        operator_mode = $script:OperatorMode
        authorization_consumed = $AuthorizationConsumed
        transfer_equivalent = [bool]$script:Config.transfer_equivalent
        invocation_count = $InvocationCount
        recovery_exporter_invocations = 0
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
    $target = Join-Path $script:EvidenceDirectory $FileName
    if (Test-Path -LiteralPath $target) { return }
    $json = $summary | ConvertTo-Json -Depth 5
    $temporary = Join-Path $script:EvidenceDirectory (".w5-summary-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [System.IO.File]::WriteAllText($temporary, $json + "`n", [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $target
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

try {
    if ($PreflightOnly -and $RecoveryOnly) { Fail-Gate "configuration" }
    if ($RecoveryOnly) {
        $script:OperatorMode = "recovery"
        $script:SummaryFileName = "w5-b-sanitized-recovery-summary.json"
    }
    $configPath = Assert-PlainExistingPath (Full-Path $OperatorConfig) $false
    $configText = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::UTF8)
    $lexicalFields = @(Get-StrictTopLevelJsonPropertyNames $configText | Sort-Object)
    try { $script:Config = $configText | ConvertFrom-Json }
    catch { Fail-Gate "configuration" }
    $requiredFields = @(
        "format_version", "owner_authorized", "transfer_equivalent", "expected_execution_head",
        "repo_root", "python_executable", "state_dir", "max_pages", "raw_root",
        "reliability_profile_path", "chunking_profile_path", "jira_relation_profile_path",
        "tokenizer_assets_dir", "space_key", "root_page_id", "dataset_root_a",
        "dataset_root_b", "evidence_dir", "git_repository", "git_branch", "git_commit",
        "live_phase_timeout_seconds", "offline_phase_timeout_seconds",
        "max_child_working_set_bytes"
    ) | Sort-Object
    $observedFields = @($script:Config.PSObject.Properties.Name | Sort-Object)
    if (($requiredFields -join "`n") -ne ($observedFields -join "`n") -or
        ($requiredFields -join "`n") -ne ($lexicalFields -join "`n")) {
        Fail-Gate "configuration"
    }
    Assert-ExactObject $script:Config $requiredFields "configuration"
    foreach ($field in @(
        "format_version", "expected_execution_head", "repo_root", "python_executable",
        "state_dir", "raw_root", "reliability_profile_path", "chunking_profile_path",
        "jira_relation_profile_path", "tokenizer_assets_dir", "space_key", "root_page_id",
        "dataset_root_a", "dataset_root_b", "evidence_dir", "git_repository",
        "git_branch", "git_commit"
    )) { Assert-ExactString $script:Config.$field "configuration" }
    Assert-ExactBoolean $script:Config.owner_authorized "configuration"
    Assert-ExactBoolean $script:Config.transfer_equivalent "configuration"
    foreach ($field in @(
        "max_pages", "live_phase_timeout_seconds", "offline_phase_timeout_seconds",
        "max_child_working_set_bytes"
    )) { Assert-ExactInteger $script:Config.$field "configuration" 1 }
    if ($script:Config.format_version -ne "w5-b-root1-one-shot-v1" -or
        ((-not $PreflightOnly -and -not $RecoveryOnly) -and $script:Config.owner_authorized -ne $true) -or
        $script:Config.transfer_equivalent -ne $true) {
        Fail-Gate "authorization"
    }
    if ([int64]$script:Config.live_phase_timeout_seconds -lt 60 -or
        [int64]$script:Config.live_phase_timeout_seconds -gt 86400 -or
        [int64]$script:Config.offline_phase_timeout_seconds -lt 60 -or
        [int64]$script:Config.offline_phase_timeout_seconds -gt 86400 -or
        [int64]$script:Config.max_child_working_set_bytes -lt 1073741824 -or
        [int64]$script:Config.max_child_working_set_bytes -gt 68719476736) {
        Fail-Gate "resource_budget"
    }
    if (-not $RecoveryOnly) {
        try {
            $physicalMemory = [int64](Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory
        }
        catch { Fail-Gate "resource_budget" }
        if ($physicalMemory -le 2147483648 -or
            [int64]$script:Config.max_child_working_set_bytes -gt ($physicalMemory - 2147483648)) {
            Fail-Gate "resource_budget"
        }
    }

    $script:RepoRoot = Assert-PlainExistingPath (Full-Path $script:Config.repo_root) $true
    if (Is-Within $script:RepoRoot $configPath) { Fail-Gate "configuration" }
    if ($RecoveryOnly) {
        $script:PythonExecutable = Full-Path $script:Config.python_executable
    } else {
        $script:PythonExecutable = Assert-PlainExistingPath (Full-Path $script:Config.python_executable) $false
    }
    $head = (& git -C $script:RepoRoot rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$' -or $head -ne $script:Config.expected_execution_head) {
        Fail-Gate "execution_head"
    }
    & git -C $script:RepoRoot diff --quiet
    if ($LASTEXITCODE -ne 0) { Fail-Gate "tracked_worktree" }
    & git -C $script:RepoRoot diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { Fail-Gate "tracked_worktree" }

    $maxPages = [int]$script:Config.max_pages
    if ($maxPages -lt 201 -or $maxPages -gt 5000) { Fail-Gate "page_bound" }
    if ([string]$script:Config.root_page_id -notmatch '^[0-9]+$' -or [string]$script:Config.space_key -notmatch '^[A-Z0-9]+$') {
        Fail-Gate "scope"
    }
    if ([string]$script:Config.git_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$script:Config.git_repository -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or
        [string]$script:Config.git_branch -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$') {
        Fail-Gate "configuration"
    }

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
    if ($RecoveryOnly) {
        $tokenizer = Full-Path $script:Config.tokenizer_assets_dir
    } else {
        $tokenizer = Assert-PlainExistingPath (Full-Path $script:Config.tokenizer_assets_dir) $true
    }
    if (Is-Within $script:RepoRoot $tokenizer) { Fail-Gate "tokenizer_boundary" }

    if ($RecoveryOnly) {
        $runtimeTargets = @(
            (Assert-PlainExistingPath (Full-Path $script:Config.state_dir) $true),
            (Assert-PlainExistingPath (Full-Path $script:Config.raw_root) $true),
            (Assert-PlainExistingPath (Full-Path $script:Config.dataset_root_a) $true),
            (Assert-PlainExistingPath (Full-Path $script:Config.dataset_root_b) $true),
            (Assert-PlainExistingPath (Full-Path $script:Config.evidence_dir) $true)
        )
        if (@($runtimeTargets | Where-Object { Is-Within $script:RepoRoot $_ }).Count -ne 0) {
            Fail-Gate "path_preflight"
        }
    }
    else {
        $runtimeTargets = @(
            (Assert-FreshExternalDirectory $script:Config.state_dir $script:RepoRoot),
            (Assert-FreshExternalDirectory $script:Config.raw_root $script:RepoRoot),
            (Assert-FreshExternalDirectory $script:Config.dataset_root_a $script:RepoRoot),
            (Assert-FreshExternalDirectory $script:Config.dataset_root_b $script:RepoRoot),
            (Assert-FreshExternalDirectory $script:Config.evidence_dir $script:RepoRoot)
        )
    }
    if (@($runtimeTargets | Sort-Object -Unique).Count -ne 5) { Fail-Gate "fresh_path_preflight" }
    if (-not $RecoveryOnly) {
        foreach ($target in $runtimeTargets) {
            $drive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($target))
            if (-not $drive.IsReady -or $drive.AvailableFreeSpace -lt $minimumFree) { Fail-Gate "disk_budget" }
        }
    }

    if ($RecoveryOnly) {
        $stateDir, $rawRoot, $datasetA, $datasetB, $script:EvidenceDirectory = $runtimeTargets
        $privateState = Read-PrivateExportState (Join-Path $script:EvidenceDirectory "w5-b-private-export-state.json")
        $script:OriginalAuthorizationConsumed = $true
        $script:OriginalLiveInvocationCount = [int]$privateState.original_live_process_invocations
        $script:ProfileVerified = [bool]$privateState.profile_verified
        $script:TokenizerVerified = [bool]$privateState.tokenizer_verified
        $verified = Invoke-ModuleJson "knowledgenexus.foundation.cli.verify_w5_snapshot_pair" @(
            "--dataset-root-a", $datasetA, "--dataset-root-b", $datasetB
        ) $false "strict_pair_readback"
        Assert-VerificationResult $verified "strict_pair_readback"
        if ((Get-TreeDigest @($rawRoot, $stateDir)) -ne $privateState.raw_state_digest_before_export) {
            Fail-Gate "raw_state_mutation"
        }
        Write-SanitizedSummary $true $verified.counts $true $script:OriginalLiveInvocationCount $script:SummaryFileName
        [Console]::Out.WriteLine('{"all_gates_passed":true,"exporter_invocations":0,"read_only_verifier_invocations":1,"status":"recovery_complete"}')
        exit 0
    }

    $testArguments = @(
        "-B", "-m", "pytest", "-p", "no:cacheprovider",
        "tests/foundation/cli/test_w4_c2_composition.py",
        "tests/foundation/application/use_cases/test_confluence_subtree_capture_resume.py",
        "tests/foundation/cli/test_confluence_subtree_cli.py",
        "tests/foundation/cli/test_export_m10_snapshot_cli.py",
        "tests/foundation/cli/test_m10_operator_cli_e2e.py",
        "tests/foundation/integration/test_w5_a_runbook_artifacts.py",
        "tests/foundation/application/use_cases/test_evaluate_foundation_gates.py",
        "tests/foundation/application/use_cases/test_capture_delta_inventory.py",
        "tests/foundation/application/use_cases/test_project_m10_delta.py",
        "tests/foundation/application/use_cases/test_export_m10_snapshot.py",
        "tests/foundation/cli/test_evaluate_foundation_gates_cli.py",
        "tests/foundation/domain/models/test_foundation_gate.py",
        "tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py",
        "tests/foundation/domain/rules/test_snapshot_readback.py",
        "tests/foundation/infrastructure/config/test_bge_m3_tokenizer_assets.py",
        "tests/foundation/infrastructure/tokenization/test_bge_m3_local_tokenizer.py",
        "tests/architecture", "--tokenizer-assets-dir", $tokenizer, "-q"
    )
    [void](Invoke-PythonProcess -Arguments $testArguments -Live $false -Stage "offline_preflight_tests" -ExpectJson $false)
    $syntaxProbe = 'import ast,pathlib,tokenize; files=tuple(pathlib.Path(root).rglob("*.py") for root in ("src","tests")); [ast.parse(tokenize.open(str(path)).read(), filename=str(path)) for group in files for path in group]'
    [void](Invoke-PythonProcess -Arguments @("-B", "-c", $syntaxProbe) -Live $false -Stage "syntax_probe" -ExpectJson $false)
    $script:ProfileVerified = $true
    $script:TokenizerVerified = $true

    if ($PreflightOnly) {
        [Console]::Out.WriteLine('{"all_gates_passed":true,"authorization_consumed":false,"status":"preflight_complete"}')
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($env:CONFLUENCE_BASE_URL) -or [string]::IsNullOrWhiteSpace($env:CONFLUENCE_PAT)) {
        Fail-Gate "live_credentials"
    }

    foreach ($target in $runtimeTargets) { [void](New-Item -ItemType Directory -Path $target) }
    foreach ($target in $runtimeTargets) { Assert-EmptyPlainDirectory $target }
    $stateDir, $rawRoot, $datasetA, $datasetB, $script:EvidenceDirectory = $runtimeTargets

    $common = @(
        "--state-dir", $stateDir, "--max-pages", [string]$maxPages,
        "--raw-root", $rawRoot, "--reliability-profile-path", $reliability,
        "--chunking-profile-path", $chunking, "--tokenizer-assets-dir", $tokenizer,
        "--space-key", [string]$script:Config.space_key,
        "--root-page-id", [string]$script:Config.root_page_id
    )

    $inventoryStarted = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("inventory") + $common) $true "inventory_start"
    Assert-InventoryResult $inventoryStarted "inventory_start"
    $inventory = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("inventory") + $common + @("--resume-unique")) $true "inventory_readback"
    Assert-InventoryResult $inventory "inventory_readback"
    if ([int]$inventory.selected_pages -lt 201 -or [int]$inventory.selected_pages -gt $maxPages -or
        [int]$inventoryStarted.selected_pages -ne [int]$inventory.selected_pages -or
        [string]$inventoryStarted.run_id -ne [string]$inventory.run_id) {
        Fail-Gate "inventory_readback"
    }
    $runId = [string]$inventory.run_id

    $stopped = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-pages") + $common + @("--run-id", $runId, "--stop-after-batches", "2")) $true "controlled_stop"
    Assert-CaptureResult $stopped "stopped" "controlled_stop"
    if ($stopped.status -ne "stopped" -or [int]$stopped.captured -ne 200 -or [int]$stopped.replayed -ne 0 -or [int]$stopped.failed -ne 0) {
        Fail-Gate "controlled_stop"
    }
    $resumed = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-pages") + $common + @("--run-id", $runId)) $true "capture_resume"
    Assert-CaptureResult $resumed "complete" "capture_resume"
    if ($resumed.status -ne "complete" -or [int]$resumed.replayed -ne 200 -or
        [int]$resumed.failed -ne 0 -or
        ([int]$resumed.captured + [int]$resumed.replayed + [int]$resumed.skipped) -ne [int]$inventory.selected_pages) {
        Fail-Gate "capture_resume"
    }

    $processed = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("process-pages") + $common + @("--run-id", $runId)) $false "process_pages"
    Assert-ProcessingResult $processed "process_pages"
    if ($processed.status -ne "complete" -or [int]$processed.page_count -ne [int]$inventory.selected_pages) { Fail-Gate "process_pages" }
    $drawio = Invoke-ModuleJson "knowledgenexus.foundation.cli.confluence_subtree_corpus" (@("capture-drawio") + $common + @("--run-id", $runId)) $true "capture_drawio"
    Assert-DrawioResult $drawio "capture_drawio"
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
    Write-PrivateExportState (Join-Path $script:EvidenceDirectory "w5-b-private-export-state.json") $runId $rawStateBefore

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
        $result = Invoke-ExporterModuleJson $arguments $Stage
        Assert-ExportResult $result $Stage
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
    $strictPair = Invoke-ModuleJson "knowledgenexus.foundation.cli.verify_w5_snapshot_pair" @(
        "--dataset-root-a", $datasetA, "--dataset-root-b", $datasetB
    ) $false "strict_pair_readback"
    Assert-VerificationResult $strictPair "strict_pair_readback"
    $rawStateAfter = Get-TreeDigest @($rawRoot, $stateDir)
    if ($rawStateBefore -ne $rawStateAfter) { Fail-Gate "raw_state_mutation" }

    Write-SanitizedSummary $true $exportA.counts $true $script:LiveInvocationCount $script:SummaryFileName
    [Console]::Out.WriteLine('{"all_gates_passed":true,"evidence_written":true,"status":"complete"}')
    exit 0
}
catch {
    $authorizationConsumed = $(if ($RecoveryOnly) {
        $script:OriginalAuthorizationConsumed
    } else {
        ($script:LiveInvocationCount -gt 0)
    })
    $reportedInvocations = $(if ($RecoveryOnly) {
        $script:OriginalLiveInvocationCount
    } else {
        $script:LiveInvocationCount
    })
    try {
        Write-SanitizedSummary $false $null $authorizationConsumed $reportedInvocations $script:SummaryFileName
    }
    catch { }
    $payload = (New-FailurePayload $authorizationConsumed) | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($payload)
    exit 1
}
