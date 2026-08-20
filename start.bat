@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

REM ============================================================
REM  KnowledgeNexus - System Startup Script
REM  Khoi tao va chay toan bo he thong RAG
REM  Su dung: start.bat [start|stop|status|restart]
REM ============================================================

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "API_HOST=127.0.0.1"
set "API_BIND_HOST=0.0.0.0"
set "API_PORT=8000"
set "QDRANT_PORT=6333"
set "API_URL=http://%API_HOST%:%API_PORT%"
set "QDRANT_START_BAT=C:\qdrant\QdrantStart.bat"

REM --- Auto-detect Python Command (Multi-layered Robust Detection) ---
set "PYTHON_CMD="

REM 1. Check if virtual environment (.venv) exists in the project root
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
    goto :python_detected
)
if exist "%PROJECT_ROOT%\venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\venv\Scripts\python.exe"
    goto :python_detected
)

REM 2. Scan %LocalAppData%\Programs\Python\Python* for the latest Python installation
if defined LocalAppData (
    for /f "delims=" %%I in ('dir /b /ad "%LocalAppData%\Programs\Python\Python*" 2^>nul') do (
        if exist "%LocalAppData%\Programs\Python\%%I\python.exe" (
            set "PYTHON_CMD=%LocalAppData%\Programs\Python\%%I\python.exe"
        )
    )
    if defined PYTHON_CMD goto :python_detected
)

REM 3. Fallback to Windows Python Launcher 'py' if available
where py >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_CMD=py"
    goto :python_detected
)

REM 4. Fallback to 'python' from PATH if it works (validating it's not the Microsoft Store stub)
where python >nul 2>&1
if !errorlevel! equ 0 (
    python -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        goto :python_detected
    )
)

REM 5. Final fallback
set "PYTHON_CMD=python"

:python_detected
echo       Using Python command: %PYTHON_CMD%

REM --- MCP HTTP Server Configuration ---
set "MCP_TRANSPORT=http"
set "MCP_HTTP_HOST=0.0.0.0"
set "MCP_HTTP_PORT=8787"
set "MCP_HTTP_ALLOWED_HOSTS="

REM Detect LAN IP for display
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R /C:"IPv4 Address"') do (
    for /f "tokens=* delims= " %%b in ("%%a") do (
        if not defined LAN_IP set "LAN_IP=%%b"
    )
)
if not defined LAN_IP set "LAN_IP=%API_HOST%"

REM Parse argument
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"

if /I "%ACTION%"=="stop" goto :stop
if /I "%ACTION%"=="status" goto :status
if /I "%ACTION%"=="restart" (
    call :stop
    ping -n 3 127.0.0.1 >nul
    goto :start
)

if /I "%ACTION%"=="start" goto :start

echo [ERROR] Unknown action: %ACTION%
echo Usage: start.bat [start^|stop^|status^|restart]
exit /b 1

REM ============================================================
REM  START
REM ============================================================
:start
echo.
echo ============================================================
echo   KnowledgeNexus - Starting System
echo ============================================================
echo.

REM --- Step 1: Check Qdrant ---
echo [1/5] Checking Qdrant on port %QDRANT_PORT%...
curl -s http://localhost:%QDRANT_PORT%/healthz >nul 2>&1
if !errorlevel! equ 0 (
    echo       ✓ Qdrant is running
    goto :qdrant_done
)

echo       ✗ Qdrant is NOT running

REM Check if C:\qdrant directory exists and start qdrant with config
if exist "C:\qdrant\config.yaml" (
    echo       Starting Qdrant from C:\qdrant...
    start "Qdrant" cmd /c "cd /D C:\qdrant && qdrant --config-path "C:\\qdrant\\config.yaml""
) else (
    echo       ✗ Cannot find C:\qdrant\config.yaml
    echo       Please ensure Qdrant is installed to C:\qdrant with config.yaml
    exit /b 1
)

echo       Waiting for Qdrant to start...
set "q_retries=0"

:wait_qdrant
ping -n 2 127.0.0.1 >nul
curl -s http://localhost:%QDRANT_PORT%/healthz >nul 2>&1
if !errorlevel! equ 0 (
    echo       ✓ Qdrant started successfully
    goto :qdrant_done
)
set /a q_retries+=1
if !q_retries! lss 10 goto :wait_qdrant

echo       ✗ Failed to start Qdrant within 10 seconds
exit /b 1

:qdrant_done

REM --- Step 2: Check API server ---
echo.
echo [2/5] Checking KnowledgeNexus API on port %API_PORT%...
curl -s http://%API_HOST%:%API_PORT%/api/v1/health >nul 2>&1
if !errorlevel! equ 0 (
    echo       ✓ API server is already running
    goto :api_done
)

echo       ✗ API server is NOT running

REM Install Python dependencies using the detected Python interpreter (pip will skip already-installed packages)
echo       Installing Python dependencies...
%PYTHON_CMD% -m pip install -r "%PROJECT_ROOT%\requirements.txt"

echo       Starting KnowledgeNexus API (binding to %API_BIND_HOST%:%API_PORT%)...

where knowledgenexus >nul 2>&1
if !errorlevel! equ 0 (
    start "KnowledgeNexus API" knowledgenexus
) else (
    start "KnowledgeNexus API" cmd /c "set PYTHONPATH=%PROJECT_ROOT%\src && %PYTHON_CMD% -m uvicorn knowledgenexus.presentation.api.app:app --host %API_BIND_HOST% --port %API_PORT%"
)

echo       Waiting for server to start...
set "retries=0"

:wait_api
ping -n 2 127.0.0.1 >nul
curl -s http://%API_HOST%:%API_PORT%/api/v1/health >nul 2>&1

if !errorlevel! equ 0 (
    echo       ✓ API server started successfully
    goto :api_done
)
set /a retries+=1
if !retries! lss 20 goto :wait_api
echo       ✗ API server failed to start within 20 seconds
exit /b 1

:api_done

REM --- Step 3: Health check ---
echo.
echo [3/5] Running health check...
for /f "delims=" %%i in ('curl -s http://%API_HOST%:%API_PORT%/api/v1/health 2^>nul') do set "HEALTH=%%i"
echo       !HEALTH!

REM --- Step 4: Start MCP HTTP Server ---
echo.
echo [4/5] Starting MCP HTTP Server on port %MCP_HTTP_PORT%...

REM Check if MCP dependencies and build exist
pushd "%PROJECT_ROOT%\mcp"

REM Step 1: Check and install node_modules if missing
if not exist "node_modules" (
    echo       MCP dependencies not found. Installing...
    call npm install
)

REM Step 2: Check and build if build/index.js is missing
if not exist "build\index.js" (
    echo       MCP build not found. Building...
    call npm run build
)

popd

REM Verify build succeeded
if not exist "%PROJECT_ROOT%\mcp\build\index.js" (
    echo       ✗ MCP build failed
    echo       You can build manually: cd mcp ^&^& npm install ^&^& npm run build
    goto :mcp_skip
)

REM Check if MCP server is already running
curl -s -X POST http://localhost:%MCP_HTTP_PORT%/mcp -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"healthcheck\",\"version\":\"1.0\"}},\"id\":1}" >nul 2>&1
if !errorlevel! equ 0 (
    echo       ✓ MCP HTTP Server is already running
    goto :mcp_done
)

echo       Starting MCP HTTP Server (transport: %MCP_TRANSPORT%, bind: %MCP_HTTP_HOST%:%MCP_HTTP_PORT%)...
REM Use LAN IP for remote access, not localhost
set "MCP_API_URL=http://%LAN_IP%:%API_PORT%"
start "MCP HTTP Server" powershell -NoExit -Command "$env:MCP_TRANSPORT='%MCP_TRANSPORT%'; $env:MCP_HTTP_HOST='%MCP_HTTP_HOST%'; $env:MCP_HTTP_PORT='%MCP_HTTP_PORT%'; $env:KNOWLEDGENEXUS_API_URL='%MCP_API_URL%'; Set-Location '%PROJECT_ROOT%\mcp'; node build/index.js"

echo       Waiting for MCP server to start...
set "m_retries=0"

:wait_mcp
ping -n 2 127.0.0.1 >nul
curl -s -X POST http://localhost:%MCP_HTTP_PORT%/mcp -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"healthcheck\",\"version\":\"1.0\"}},\"id\":1}" >nul 2>&1
if !errorlevel! equ 0 (
    echo       ✓ MCP HTTP Server started successfully
    goto :mcp_done
)
set /a m_retries+=1
if !m_retries! lss 10 goto :wait_mcp

echo       ✗ MCP HTTP Server failed to start within 10 seconds
echo       Check mcp/build/index.js exists and node is in PATH
goto :mcp_skip

:mcp_done
echo.
echo       MCP HTTP Server (local):  http://localhost:%MCP_HTTP_PORT%/mcp
echo       MCP HTTP Server (LAN):    http://%LAN_IP%:%MCP_HTTP_PORT%/mcp

:mcp_skip

REM --- Step 5: Done ---
echo.
echo [5/5] System is ready!
echo.
echo ============================================================
echo   KnowledgeNexus is running!
echo ============================================================
echo.
echo   API Base URL (local):   http://127.0.0.1:%API_PORT%
echo   API Base URL (LAN):     http://%LAN_IP%:%API_PORT%
echo   MCP HTTP Server:         http://%LAN_IP%:%MCP_HTTP_PORT%/mcp
echo   Swagger UI:              http://%LAN_IP%:%API_PORT%/docs
echo   ReDoc:                   http://%LAN_IP%:%API_PORT%/redoc
echo   Health:                  http://%LAN_IP%:%API_PORT%/api/v1/health
echo   Portal Website:          %PROJECT_ROOT%\portal\index.html
echo.
echo   --- API Endpoints ---
echo   GET  /api/v1/health           - Health check
echo   POST /api/v1/retrieve          - Semantic search
echo   GET  /api/v1/documents         - List documents
echo   DEL  /api/v1/documents/{id}    - Delete document
echo   POST /api/v1/store/chunks      - Store chunks
echo   GET  /api/v1/store/stats       - Store statistics
echo.
echo   --- Integration Guide ---
echo   Website:       Use API_URL in fetch() calls (CORS enabled)
echo   AgentBuilder:  Point to http://%LAN_IP%:%API_PORT%/api/v1/retrieve
echo   Cline/MCP:     KNOWLEDGENEXUS_API_URL=http://%LAN_IP%:%API_PORT%
echo.
echo   --- MCP Client Config (for other machines) ---
echo   Add to MCP client settings (Cline, Claude Code, etc.):
echo   {
echo     "knowledgenexus": {
echo       "type": "http",
echo       "url": "http://%LAN_IP%:%MCP_HTTP_PORT%/mcp"
echo     }
echo   }
echo.
echo   --- LAN Access ---
echo   From other machines on the same network, use:
echo     API:  http://%LAN_IP%:%API_PORT%
echo     MCP:  http://%LAN_IP%:%MCP_HTTP_PORT%/mcp
echo   Open Windows Firewall ports %API_PORT%, %QDRANT_PORT%, %MCP_HTTP_PORT% if access is blocked.
echo.
echo   To stop: start.bat stop
echo.
exit /b 0

REM ============================================================
REM  STOP
REM ============================================================
:stop
echo.
echo ============================================================
echo   Stopping KnowledgeNexus System
echo ============================================================
echo.

echo [1/3] Stopping MCP HTTP Server (port %MCP_HTTP_PORT%)...
powershell -Command "Get-NetTCPConnection -LocalPort %MCP_HTTP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host '       Killed PID:' $_ }"
echo       ✓ Done

echo [2/3] Stopping KnowledgeNexus API (port %API_PORT%)...
powershell -Command "Get-NetTCPConnection -LocalPort %API_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host '       Killed PID:' $_ }"
echo       ✓ Done

echo [3/3] Stopping Qdrant (port %QDRANT_PORT%)...
powershell -Command "Get-NetTCPConnection -LocalPort %QDRANT_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host '       Killed PID:' $_ }"
echo       ✓ Done

echo.
echo   System stopped.
echo.
exit /b 0

REM ============================================================
REM  STATUS
REM ============================================================
:status
echo.
echo ============================================================
echo   KnowledgeNexus - System Status
echo ============================================================
echo.

echo [Qdrant]   Port %QDRANT_PORT%:
curl -s http://localhost:%QDRANT_PORT%/healthz >nul 2>&1
if !errorlevel! equ 0 (
    echo   ✓ Running
) else (
    echo   ✗ Stopped
)

echo.
echo [API]      Port %API_PORT%:
curl -s http://%API_HOST%:%API_PORT%/api/v1/health 2>nul
if !errorlevel! neq 0 (
    echo   ✗ Stopped
)

echo.
echo [MCP HTTP] Port %MCP_HTTP_PORT%:
curl -s -X POST http://localhost:%MCP_HTTP_PORT%/mcp -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"healthcheck\",\"version\":\"1.0\"}},\"id\":1}" >nul 2>&1
if !errorlevel! equ 0 (
    echo   ✓ Running
) else (
    echo   ✗ Stopped
)

echo.
echo ============================================================
exit /b 0
