@echo off
setlocal

set "PMO_SOURCE=%~dp0"
set "PMO_BACKUP_ROOT=%USERPROFILE%\Desktop\PMO_BOT_BACKUPS"

echo ============================================================
echo PMO BOT FULL BACKUP
echo Source: %PMO_SOURCE%
echo Backup root: %PMO_BACKUP_ROOT%
echo ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$source = (Resolve-Path -LiteralPath $env:PMO_SOURCE).Path; " ^
  "$backupRoot = $env:PMO_BACKUP_ROOT; " ^
  "$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'; " ^
  "$dest = Join-Path $backupRoot ('PMO_BOT_FULL_BACKUP_' + $stamp); " ^
  "New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null; " ^
  "Copy-Item -LiteralPath $source -Destination $dest -Recurse -Force; " ^
  "$items = (Get-ChildItem -LiteralPath $dest -Recurse -Force | Measure-Object).Count; " ^
  "Write-Host ''; " ^
  "Write-Host 'PMO BOT backup complete.'; " ^
  "Write-Host ('Backup: ' + $dest); " ^
  "Write-Host ('Items copied: ' + $items);"

echo.
pause
