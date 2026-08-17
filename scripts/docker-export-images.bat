@echo off
REM Run this on a machine WITH Docker + internet access, after building the
REM stack once (docker compose build). It bundles all 3 images used by
REM docker-compose.yml into portable .tar files under docker\vendor\, so a
REM machine WITHOUT internet access can later "docker load" them and run
REM "docker compose up -d" with zero network calls (no Docker Hub pull, no
REM rebuild).
setlocal

cd /d "%~dp0.."

set OUT_DIR=docker\vendor
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

set QDRANT_IMAGE=qdrant/qdrant:v1.12.6
set API_IMAGE=knowledgenexus-api:latest
set MCP_IMAGE=knowledgenexus-mcp:latest

echo ==^> Pulling %QDRANT_IMAGE% from Docker Hub...
docker pull %QDRANT_IMAGE% || exit /b 1

echo ==^> Building api/mcp images (docker compose build)...
docker compose build api mcp || exit /b 1

echo ==^> Saving images to %OUT_DIR%\*.tar ...
docker save -o "%OUT_DIR%\qdrant.tar" %QDRANT_IMAGE% || exit /b 1
docker save -o "%OUT_DIR%\knowledgenexus-api.tar" %API_IMAGE% || exit /b 1
docker save -o "%OUT_DIR%\knowledgenexus-mcp.tar" %MCP_IMAGE% || exit /b 1

echo ==^> Done. Copy the whole "%OUT_DIR%" folder (plus this repo) to the
echo     offline machine, then run scripts\docker-import-images.bat there.
dir "%OUT_DIR%"

endlocal
