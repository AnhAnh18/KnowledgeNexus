@echo off
REM Gathers the minimal set of files an offline/air-gapped target machine
REM needs to run the Docker stack.
REM 
REM NOTE: Models are NOT included in this package. They are stored externally
REM at D:/KnowledgeNexus_Data/models/ and mounted via docker-compose.yml volume.
REM 
REM Run scripts\docker-export-images.bat FIRST so docker\vendor\*.tar exist.
setlocal enabledelayedexpansion

cd /d "%~dp0.."

set PKG_DIR=dist\knowledgenexus-deploy
set ZIP_PATH=dist\knowledgenexus-deploy.zip

if not exist "docker\vendor\qdrant.tar" (
    echo Missing docker\vendor\qdrant.tar -- run scripts\docker-export-images.bat first.
    exit /b 1
)
if not exist "docker\vendor\knowledgenexus-api.tar" (
    echo Missing docker\vendor\knowledgenexus-api.tar -- run scripts\docker-export-images.bat first.
    exit /b 1
)
if not exist "docker\vendor\knowledgenexus-mcp.tar" (
    echo Missing docker\vendor\knowledgenexus-mcp.tar -- run scripts\docker-export-images.bat first.
    exit /b 1
)
if not exist ".env" (
    echo Missing .env -- fill it in before packaging.
    exit /b 1
)
if not exist ".env.docker" (
    echo Missing .env.docker -- copy .env.docker.example to .env.docker and fill it in first.
    exit /b 1
)

echo ==^> This package will contain real secrets from .env (e.g. CONFLUENCE_PAT).
echo     Handle %ZIP_PATH% like a credential -- do not upload it anywhere public.
echo.

if exist "%PKG_DIR%" rmdir /s /q "%PKG_DIR%"
mkdir "%PKG_DIR%\docker\vendor"
mkdir "%PKG_DIR%\scripts"

echo ==^> Copying deploy files into %PKG_DIR% ...
copy /y "docker-compose.yml" "%PKG_DIR%\" >nul
copy /y ".env" "%PKG_DIR%\" >nul
copy /y ".env.docker" "%PKG_DIR%\" >nul
copy /y "docker\vendor\qdrant.tar" "%PKG_DIR%\docker\vendor\" >nul
copy /y "docker\vendor\knowledgenexus-api.tar" "%PKG_DIR%\docker\vendor\" >nul
copy /y "docker\vendor\knowledgenexus-mcp.tar" "%PKG_DIR%\docker\vendor\" >nul
copy /y "scripts\docker-import-images.bat" "%PKG_DIR%\scripts\" >nul
copy /y "scripts\docker-import-images.sh" "%PKG_DIR%\scripts\" >nul

echo ==^> Zipping to %ZIP_PATH% ...
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"
powershell -NoProfile -Command "Compress-Archive -Path '%PKG_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force" || exit /b 1

echo.
echo ==^> Done: %ZIP_PATH%
echo.
echo     DEPLOYMENT INSTRUCTIONS:
echo     ========================
echo     1. Copy this zip file to the offline/air-gapped machine
echo     2. Copy the models folder (D:/KnowledgeNexus_Data/models/) separately
echo        - This is NOT included in the zip (too large, ~2.3GB)
echo        - Share this folder once via network/USB
echo     3. On the target machine, extract the zip
echo     4. Run: scripts\docker-import-images.bat
echo     5. Ensure models exist at D:/KnowledgeNexus_Data/models/ on target machine
echo        (or update .env with the actual models path)
echo     6. Run: docker compose up -d
echo.
echo     NOTE: The docker-compose.yml expects models at D:/KnowledgeNexus_Data/models/
echo           If your target machine uses a different path, update .env BEFORE
echo           running docker compose up -d

endlocal
