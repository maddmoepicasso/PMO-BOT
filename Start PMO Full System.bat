@echo off
setlocal

set "PMO_PY=%~dp0"
for %%I in ("%PMO_PY%..") do set "PMO_ROOT=%%~fI\"
set "PMO_LOGS=%PMO_PY%\pmo_runtime_logs"
set "BOT_LOGS=%PMO_LOGS%\bot"
if not exist "%BOT_LOGS%" mkdir "%BOT_LOGS%"
set "BOT_OUT=%BOT_LOGS%\pmo_bot_8091_stdout.log"
set "BOT_ERR=%BOT_LOGS%\pmo_bot_8091_stderr.log"

echo ============================================================
echo PMO FULL SYSTEM STARTER
echo PMO BOT:   http://127.0.0.1:8091/control
echo ============================================================
echo.

if not exist "%PMO_PY%\pmo_bot.py" (
  echo ERROR: pmo_bot.py was not found in "%PMO_PY%".
  pause
  exit /b 1
)

echo Stopping old PMO BOT web server on port 8091 if it is already running...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ports = 8091; " ^
  "foreach ($port in $ports) { " ^
  "  $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; " ^
  "  foreach ($owner in $owners) { if ($owner) { Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue } } " ^
  "}"

timeout /t 2 /nobreak >nul

echo Starting PMO BOT...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$env:PYTHONUTF8='1'; " ^
  "$env:PYTHONIOENCODING='utf-8'; " ^
  "$py = $env:PMO_PY; " ^
  "Start-Process -FilePath 'python' -ArgumentList 'pmo_bot.py' -WorkingDirectory $py -WindowStyle Hidden -RedirectStandardOutput $env:BOT_OUT -RedirectStandardError $env:BOT_ERR;"

timeout /t 5 /nobreak >nul

echo.
echo Checking PMO health...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$bot = $false; " ^
  "try { $bot = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8091/api/health' -TimeoutSec 8).StatusCode -eq 200 } catch {}; " ^
  "Write-Host ('PMO BOT   : ' + $(if ($bot) {'ONLINE'} else {'OFFLINE'})); " ^
  "if (-not $bot) { exit 2 }"

if errorlevel 2 (
  echo.
  echo PMO BOT did not pass health check.
  echo PMO BOT log:   "%BOT_ERR%"
  pause
  exit /b 2
)

echo.
echo PMO BOT is running.
echo Open PMO BOT:   http://127.0.0.1:8091/control
echo.
pause
