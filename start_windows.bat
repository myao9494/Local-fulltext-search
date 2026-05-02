@echo off
setlocal

rem Windows launcher for Local Fulltext Search.
rem Stops the process listening on the configured port, then starts backend/run.py.

set "APP_ROOT=%~dp0"
set "BACKEND_DIR=%APP_ROOT%backend"
set "SEARCH_APP_HOST=127.0.0.1"
if "%SEARCH_APP_PORT%"=="" set "SEARCH_APP_PORT=8079"
set "SEARCH_APP_LAUNCHER_AUTOSTART=1"

echo [Local Fulltext Search] Checking port %SEARCH_APP_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = [int]$env:SEARCH_APP_PORT; $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique); foreach ($processId in $processIds) { if ($processId -and $processId -ne $PID) { $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue; if ($proc) { Write-Host ('[Local Fulltext Search] Stop PID {0}: {1}' -f $processId, $proc.ProcessName); Stop-Process -Id $processId -Force; } } }"

if errorlevel 1 (
  echo [Local Fulltext Search] Failed to check or release the port.
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\run.py" (
  echo [Local Fulltext Search] backend\run.py was not found: "%BACKEND_DIR%"
  pause
  exit /b 1
)

cd /d "%BACKEND_DIR%"
echo [Local Fulltext Search] Starting http://127.0.0.1:%SEARCH_APP_PORT%/
python run.py

echo.
echo [Local Fulltext Search] Stopped.
pause
