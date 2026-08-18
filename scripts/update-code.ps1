# PowerShell script to update the KnowledgeNexus application code.
#
# Usage:
#   .\updates\update-code.ps1
#
# This script:
# 1. Finds the latest knowledgenexus-code-v*.zip in the updates/ folder
# 2. Extracts it to the installation root (parent of updates/)
# 3. Installs Python dependencies from requirements.txt
#
# Client workflow:
# 1. Copy new zip file to: D:/KnowledgeNexus/updates/
# 2. Run: .\updates\update-code.ps1
# 3. Restart: .\start.bat stop && .\start.bat start

# Resolve paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Split-Path -Parent $scriptDir  # Parent of updates/

# Find the latest zip file in updates/ folder
$zipFile = Get-ChildItem -Path $scriptDir -Filter "knowledgenexus-code-v*.zip" |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1

if (-not $zipFile) {
    Write-Warning "No knowledgenexus-code-v*.zip found in $scriptDir"
    Write-Host "Please copy the new package zip file to the updates/ folder first."
    exit 1
}

Write-Host "Found package: $($zipFile.Name)"
Write-Host "Extracting to: $installDir"

# Remove existing source directory before extracting
$srcDir = Join-Path $installDir "src"
if (Test-Path $srcDir) {
    Write-Host "Removing old src/..."
    Remove-Item -Recurse -Force $srcDir
}

# Remove old MCP directory
$mcpDir = Join-Path $installDir "mcp"
if (Test-Path $mcpDir) {
    Write-Host "Removing old mcp/..."
    Remove-Item -Recurse -Force $mcpDir
}

# Remove old configuration files
$configFiles = @("pyproject.toml", "requirements.txt", "README.md", ".env.example", "start.bat")
foreach ($cfg in $configFiles) {
    $cfgPath = Join-Path $installDir $cfg
    if (Test-Path $cfgPath) {
        Remove-Item -Force $cfgPath
    }
}

# Extract new code package
Expand-Archive -Path $zipFile.FullName -DestinationPath $installDir -Force
Write-Host "Code extracted successfully."

# Install/upgrade Python dependencies if requirements.txt exists
$requirementsPath = Join-Path $installDir "requirements.txt"
if (Test-Path $requirementsPath) {
    Write-Host "Installing/upgrading Python dependencies..."
    try {
        pip install -r $requirementsPath -U
        Write-Host "Dependencies installed successfully."
    } catch {
        Write-Warning "Failed to install dependencies: $_"
    }
} else {
    Write-Warning "requirements.txt not found; skipping dependency installation."
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Update completed successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Stop the system: .\start.bat stop"
Write-Host "  2. Start the system: .\start.bat start"
Write-Host ""
