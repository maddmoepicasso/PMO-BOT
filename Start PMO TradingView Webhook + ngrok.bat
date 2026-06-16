@echo off
setlocal

set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PMO_LOGS=%PMO_ROOT%Logs"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PMO_WEBHOOK_URL=http://127.0.0.1:8091/tradingview"
set "PMO_NGROK_DOMAIN=next-vastly-parasite.ngrok-free.dev"
set "PMO_PUBLIC_WEBHOOK=https://%PMO_NGROK_DOMAIN%/tradingview"

rem Set this to 1 only if ngrok says the reserved endpoint is already online
rem and you intentionally want load-balanced pooling for the same endpoint.
set "PMO_NGROK_POOLING=0"

echo ============================================================
echo PMO BOT TRADINGVIEW WEBHOOK + NGROK
echo Root: %PMO_ROOT%
echo Python: %PMO_PY%
echo Local webhook: %PMO_WEBHOOK_URL%
echo Public webhook: %PMO_PUBLIC_WEBHOOK%
echo ============================================================
echo.

if not exist "%PMO_PY%\pmo_bot.py" (
    echo ERROR: pmo_bot.py was not found in "%PMO_PY%".
    echo Check that this BAT file is still inside the main PMO_BOT folder.
    pause
    exit /b 1
)

if not exist "%PMO_LOGS%" mkdir "%PMO_LOGS%"

echo Checking PMO BOT terminal/webhook on port 8091...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri '%PMO_WEBHOOK_URL%' -TimeoutSec 8).StatusCode -in 200,405 } catch { $ok = $false }; " ^
    "if ($ok) { Write-Host 'PMO webhook: ONLINE' } else { Write-Host 'PMO webhook: STARTING'; exit 2 }"

if errorlevel 2 (
    echo Starting PMO BOT webhook server on 8091...
    start "PMO BOT TradingView Webhook" /D "%PMO_PY%" cmd /c "set ""PYTHONUTF8=1"" && set ""PYTHONIOENCODING=utf-8"" && python ""%PMO_PY%\pmo_bot.py"" --webhook 1>""%PMO_LOGS%\webhook_start_stdout.txt"" 2>""%PMO_LOGS%\webhook_start_stderr.txt"""
    echo Waiting for local webhook to come online...
    timeout /t 8 /nobreak >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri '%PMO_WEBHOOK_URL%' -TimeoutSec 8).StatusCode -in 200,405 } catch { $ok = $false }; " ^
    "if ($ok) { Write-Host 'PMO webhook: ONLINE' } else { Write-Host 'PMO webhook: STARTING OR OFFLINE'; exit 2 }"

if errorlevel 2 (
    echo.
    echo The local webhook did not answer yet. Check the PMO BOT TradingView Webhook window.
    echo Local webhook should be: %PMO_WEBHOOK_URL%
    echo Logs:
    echo %PMO_LOGS%\webhook_start_stdout.txt
    echo %PMO_LOGS%\webhook_start_stderr.txt
    pause
    exit /b 1
)

echo Closing any old PMO ngrok tunnel for this endpoint...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pattern = [regex]::Escape('%PMO_NGROK_DOMAIN%'); " ^
    "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'ngrok*' -and (($_.CommandLine -match $pattern) -or ($_.CommandLine -match '(^|\\s)8091(\\s|$)')) }; " ^
    "foreach ($proc in $procs) { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }"

timeout /t 2 /nobreak >nul

echo Finding ngrok.exe...
set "PMO_NGROK="
where ngrok.exe >nul 2>nul
if not errorlevel 1 set "PMO_NGROK=ngrok.exe"
if not defined PMO_NGROK if exist "%PMO_ROOT%ngrok.exe" set "PMO_NGROK=%PMO_ROOT%ngrok.exe"
if not defined PMO_NGROK if exist "%PMO_PY%\ngrok.exe" set "PMO_NGROK=%PMO_PY%\ngrok.exe"
if not defined PMO_NGROK if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe" set "PMO_NGROK=ngrok.exe"
if not defined PMO_NGROK if exist "%LOCALAPPDATA%\ngrok\ngrok.exe" set "PMO_NGROK=%LOCALAPPDATA%\ngrok\ngrok.exe"

if not defined PMO_NGROK (
    echo.
    echo ngrok.exe was not found in PATH, PMO_BOT, PMO_BOT\Python, WindowsApps, or AppData\Local\ngrok.
    echo The local TradingView webhook is still running here:
    echo %PMO_WEBHOOK_URL%
    echo.
    echo Put ngrok.exe inside the PMO_BOT folder or install ngrok, then run this BAT again.
    pause
    exit /b 1
)

set "PMO_POOLING_ARG="
if "%PMO_NGROK_POOLING%"=="1" set "PMO_POOLING_ARG= --pooling-enabled"

echo.
echo Starting ngrok for TradingView alerts...
echo Public TradingView webhook URL:
echo %PMO_PUBLIC_WEBHOOK%
echo.
echo If ERR_NGROK_334 appears, your reserved endpoint is already online.
echo Fix that by stopping the old endpoint in ngrok dashboard, or set PMO_NGROK_POOLING=1 above.
echo.
"%PMO_NGROK%" http 8091 --url=https://%PMO_NGROK_DOMAIN%%PMO_POOLING_ARG%

pause

