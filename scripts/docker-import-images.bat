@echo off
REM Run this on the OFFLINE/air-gapped machine, after copying docker\vendor\*.tar
REM here from a machine that ran scripts\docker-export-images.bat. Loads all 3
REM images into the local Docker image cache so "docker compose up -d" runs
REM with no network access at all (no Docker Hub pull, no build).
setlocal

cd /d "%~dp0.."

set IN_DIR=docker\vendor

for %%F in (qdrant.tar knowledgenexus-api.tar knowledgenexus-mcp.tar) do (
    if not exist "%IN_DIR%\%%F" (
        echo Missing %IN_DIR%\%%F -- did you copy docker\vendor\ from the export machine?
        exit /b 1
    )
)

echo ==^> Loading %IN_DIR%\qdrant.tar ...
docker load -i "%IN_DIR%\qdrant.tar" || exit /b 1
echo ==^> Loading %IN_DIR%\knowledgenexus-api.tar ...
docker load -i "%IN_DIR%\knowledgenexus-api.tar" || exit /b 1
echo ==^> Loading %IN_DIR%\knowledgenexus-mcp.tar ...
docker load -i "%IN_DIR%\knowledgenexus-mcp.tar" || exit /b 1

echo ==^> Done. Images are now in the local Docker cache -- you can run:
echo     docker compose up -d
echo     (it will NOT pull or rebuild, since the tags already match)

endlocal
