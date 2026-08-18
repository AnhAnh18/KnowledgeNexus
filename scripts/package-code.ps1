# PowerShell script to package the KnowledgeNexus application code into a versioned zip archive.
#
# Usage:
#   .\package-code.ps1 [-Version <version>]
#
# The script zips:
# - 'src/' directory (Python source code - production code only)
# - 'mcp/' directory (MCP server - TypeScript/Node.js)
# - 'portal/' directory (Portal web client - HTML/CSS/JS)
# - Essential project files (pyproject.toml, requirements.txt, README.md, .env.example, start.bat)
#
# Note: eval/ is NOT included - it's for development/testing only.
# placed in the 'packages' directory.

param(
    [string]$Version
)

# Resolve repository root (assumes this script is located in the 'scripts' directory)
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent

# Determine version
if (-not $Version) {
    $versionFile = Join-Path $repoRoot "VERSION"
    if (Test-Path $versionFile) {
        $Version = Get-Content $versionFile -Raw | Trim
    } else {
        $Version = "1.0.0"
    }
}

# Paths
$srcDir = Join-Path $repoRoot "src"
$packagesDir = Join-Path $repoRoot "packages"
$zipFile = Join-Path $packagesDir "knowledgenexus-code-v$Version.zip"

# Ensure source directory exists
if (-not (Test-Path $srcDir)) {
    Write-Error "Source code directory not found at $srcDir."
    exit 1
}

# Create packages directory if it does not exist
if (-not (Test-Path $packagesDir)) {
    New-Item -ItemType Directory -Path $packagesDir | Out-Null
}

# Prepare temporary staging folder
$staging = Join-Path $repoRoot "_code_pkg_staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

# Copy source code
Copy-Item -Path $srcDir -Destination $staging -Recurse -Force

# Copy additional project files
$filesToCopy = @("pyproject.toml", "requirements.txt", "README.md", ".env.example", "start.bat")
foreach ($f in $filesToCopy) {
    $srcFile = Join-Path $repoRoot $f
    if (Test-Path $srcFile) {
        Copy-Item -Path $srcFile -Destination $staging -Force
    }
}

# Copy MCP code directory (TypeScript/Node.js MCP server)
# Exclude node_modules/ - client will run npm install
$mcpDir = Join-Path $repoRoot "mcp"
if (Test-Path $mcpDir) {
    $mcpStaging = Join-Path $staging "mcp"
    New-Item -ItemType Directory -Path $mcpStaging | Out-Null
    
    # Copy all files except node_modules
    Get-ChildItem -Path $mcpDir -Exclude "node_modules" | Copy-Item -Destination $mcpStaging -Recurse -Force
    Write-Host "MCP directory copied to staging (node_modules excluded)."
} else {
    Write-Warning "MCP directory not found at $mcpDir; skipping."
}

# Copy portal code directory (HTML/CSS/JS web client)
$portalDir = Join-Path $repoRoot "portal"
if (Test-Path $portalDir) {
    $portalStaging = Join-Path $staging "portal"
    New-Item -ItemType Directory -Path $portalStaging | Out-Null
    
    # Copy all files
    Get-ChildItem -Path $portalDir | Copy-Item -Destination $portalStaging -Recurse -Force
    Write-Host "Portal directory copied to staging."
} else {
    Write-Warning "Portal directory not found at $portalDir; skipping."
}

# Copy update-code.ps1 script (for client updates)
$updateScript = Join-Path $repoRoot "scripts\update-code.ps1"
if (Test-Path $updateScript) {
    # Create updates folder in staging
    $updatesStaging = Join-Path $staging "updates"
    New-Item -ItemType Directory -Path $updatesStaging | Out-Null
    Copy-Item -Path $updateScript -Destination $updatesStaging -Force
    Write-Host "update-code.ps1 included in updates/ folder."
}

# Create the zip archive (overwrite if exists)
Write-Host "Packaging code into $zipFile..."
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipFile -Force

# Cleanup staging
Remove-Item -Recurse -Force $staging

Write-Host "Package created successfully: $zipFile"
