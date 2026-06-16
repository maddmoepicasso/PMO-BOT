@echo off
setlocal

set "PMO_ROOT=%~dp0"
set "PMO_NGROK_DOMAIN=next-vastly-parasite.ngrok-free.dev"
set "PMO_NGROK_PORT=8080"
set "PMO_PUBLIC_WEBHOOK=https://%PMO_NGROK_DOMAIN%/tradingview"
set "PMO_NGROK_DASHBOARD=https://dashboard.ngrok.com/endpoints"

echo ============================================================
echo STOP PMO NGROK CLOUD ENDPOINT
echo Root: %PMO_ROOT%
echo Domain: %PMO_NGROK_DOMAIN%
echo Public webhook: %PMO_PUBLIC_WEBHOOK%
echo Local port: %PMO_NGROK_PORT%
echo ============================================================
echo.

echo Stopping local ngrok processes tied to PMO endpoint or port %PMO_NGROK_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$domain = '%PMO_NGROK_DOMAIN%'; " ^
    "$port = '%PMO_NGROK_PORT%'; " ^
    "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { " ^
    "($_.Name -like 'ngrok*') -and $_.CommandLine -and " ^
    "(($_.CommandLine -like ('*' + $domain + '*')) -or ($_.CommandLine -match ('(^|\\s)' + $port + '(\\s|$)'))) " ^
    "}; " ^
    "if (-not $procs) { Write-Host 'No matching local PMO ngrok processes found.' } " ^
    "foreach ($proc in $procs) { Write-Host ('Stopping ngrok PID ' + $proc.ProcessId + ': ' + $proc.CommandLine); Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo Checking whether local ngrok API is still answering...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $tunnels = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3; " ^
    "$active = @($tunnels.tunnels | Where-Object { $_.public_url -like '*%PMO_NGROK_DOMAIN%*' -or $_.config.addr -like '*%PMO_NGROK_PORT%*' }); " ^
    "if ($active.Count -gt 0) { Write-Host 'ngrok still reports an active PMO tunnel locally:'; $active | ForEach-Object { Write-Host $_.public_url }; exit 2 } " ^
    "else { Write-Host 'No PMO ngrok tunnel found in local ngrok API.' } } " ^
    "catch { Write-Host 'Local ngrok API is offline or unavailable, which usually means ngrok is stopped locally.' }"

echo.
echo If ngrok still says ERR_NGROK_334 when you start PMO again,
echo the reserved endpoint may still be online from another window,
echo another computer, or the ngrok dashboard.
echo.
echo Open ngrok dashboard endpoint page:
echo %PMO_NGROK_DASHBOARD%
echo.
choice /C YN /N /M "Open ngrok dashboard now? [Y/N] "
if errorlevel 2 goto done
start "" "%PMO_NGROK_DASHBOARD%"

:done
echo.
echo PMO ngrok stop request complete.
echo.
pause
