@echo off
setlocal
set "PMO_ROOT=%~dp0"
set "PMO_ENV=%PMO_ROOT%Python\.env"
echo ==============================================
echo PMO BOT Discord Webhook Setup
echo ==============================================
echo This saves DISCORD_WEBHOOK_URL into:
echo %PMO_ENV%
echo.
set /p PMO_DISCORD_WEBHOOK=Paste Discord webhook URL:
if "%PMO_DISCORD_WEBHOOK%"=="" (
    echo No webhook entered.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$envPath=$env:PMO_ENV; $url=$env:PMO_DISCORD_WEBHOOK; if (!(Test-Path -LiteralPath $envPath)) { New-Item -ItemType File -Path $envPath -Force | Out-Null }; $lines=Get-Content -LiteralPath $envPath -ErrorAction SilentlyContinue; $lines=@($lines | Where-Object { $_ -notmatch '^DISCORD_WEBHOOK_URL=' }); $lines += ('DISCORD_WEBHOOK_URL=' + $url); Set-Content -LiteralPath $envPath -Value $lines -Encoding UTF8"
echo Discord webhook saved locally.
pause
