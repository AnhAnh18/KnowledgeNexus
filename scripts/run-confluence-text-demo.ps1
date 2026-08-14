[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [ValidateRange(1, 5000)]
    [int]$MaxPages = 5000,

    [switch]$AllowPartialProcessing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:CONFLUENCE_PAT)) {
    throw "CONFLUENCE_PAT must be set in the current process environment."
}
if ([string]::IsNullOrWhiteSpace($env:KN_TOKENIZER_ASSETS_DIR)) {
    throw "KN_TOKENIZER_ASSETS_DIR must identify the pinned BGE-M3 tokenizer directory."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repositoryRoot "src"
$pythonPath = $env:KN_PYTHON_EXECUTABLE
if ([string]::IsNullOrWhiteSpace($pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
elseif (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "KN_PYTHON_EXECUTABLE must identify an existing Python executable."
}
Push-Location $repositoryRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $sourceRoot
    } else {
        "$sourceRoot$([IO.Path]::PathSeparator)$previousPythonPath"
    }
    $arguments = @(
        "-B", "-m", "knowledgenexus.foundation.cli.export_confluence_url_text_snapshot",
        "--url", $Url,
        "--output-root", $OutputRoot,
        "--max-pages", "$MaxPages"
    )
    if ($AllowPartialProcessing) {
        $arguments += "--allow-partial-processing"
    }
    & $pythonPath @arguments
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
