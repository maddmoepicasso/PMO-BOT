@echo off
setlocal

set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PMO_CONTROL_URL=http://127.0.0.1:8091/control"
set "PMO_WEBHOOK_URL=http://127.0.0.1:8080/tradingview"

echo ============================================================
echo STOP PMO BOT
echo Root: %PMO_ROOT%
echo Dashboard: %PMO_CONTROL_URL%
echo Local webhook: %PMO_WEBHOOK_URL%
echo ============================================================
echo.
echo This stops PMO BOT dashboard/webhook processes only.
echo Use "Stop PMO ngrok Cloud Endpoint.bat" if you also want ngrok stopped.
echo.

echo Stopping PMO BOT listeners on ports 8091 and 8080...
for %%P in (8091 8080) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
        echo Stopping PID %%A on port %%P...
        taskkill /PID %%A /F >nul 2>nul
    )
)

echo.
echo Stopping any pmo_bot.py Python process launched from this PMO_BOT folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$root = '%PMO_ROOT%'; $root = $root.TrimEnd([char]92); " ^
    "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { " ^
    "($_.Name -in @('python.exe','pythonw.exe','py.exe')) -and $_.CommandLine -and " ^
    "($_.CommandLine -match 'pmo_bot\.py') -and ($_.CommandLine -like ('*' + $root + '*')) " ^
    "}; " ^
    "if (-not $procs) { Write-Host 'No extra PMO BOT Python processes found.' } " ^
    "foreach ($proc in $procs) { Write-Host ('Stopping PMO BOT PID ' + $proc.ProcessId); Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo Checking PMO BOT dashboard status...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest -UseBasicParsing -Uri '%PMO_CONTROL_URL%' -TimeoutSec 3 | Out-Null; Write-Host 'PMO BOT may still be online. Run this BAT again or close the PMO BOT terminal window.'; exit 2 } " ^
    "catch { Write-Host 'PMO BOT dashboard is stopped or offline.' }"

echo.
echo Stop request complete.
echo.
pause
