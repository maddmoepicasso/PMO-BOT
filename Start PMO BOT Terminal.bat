@echo off
setlocal

set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PMO_CONTROL_URL=http://127.0.0.1:8091/control"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo PMO BOT COMMAND TERMINAL
echo Root: %PMO_ROOT%
echo Python: %PMO_PY%
echo Control: %PMO_CONTROL_URL%
echo ============================================================
echo.

if not exist "%PMO_PY%\pmo_bot.py" (
    echo ERROR: pmo_bot.py was not found in "%PMO_PY%".
    echo Check that this BAT file is still inside the main PMO_BOT folder.
    pause
    exit /b 1
)

echo Closing any old PMO BOT terminal on port 8091...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$owners = Get-NetTCPConnection -LocalPort 8091 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; " ^
    "foreach ($owner in $owners) { if ($owner) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue } }"

timeout /t 2 /nobreak >nul

echo Starting PMO BOT on 8091...
start "PMO BOT Command Terminal" /D "%PMO_PY%" cmd /k "set ""PYTHONUTF8=1"" && set ""PYTHONIOENCODING=utf-8"" && python ""%PMO_PY%\pmo_bot.py"""

echo Waiting for PMO BOT to come online...
timeout /t 6 /nobreak >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri '%PMO_CONTROL_URL%' -TimeoutSec 8).StatusCode -eq 200 } catch { $ok = $false }; " ^
    "if ($ok) { Write-Host 'PMO BOT: ONLINE' } else { Write-Host 'PMO BOT: STARTING OR OFFLINE'; exit 2 }"

start "" "%PMO_CONTROL_URL%"
echo.
echo PMO BOT link: %PMO_CONTROL_URL%
echo.
pause
