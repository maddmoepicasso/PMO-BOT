@echo off
setlocal
title PMO Audits and Reports

set "PMO_DIR=%~dp0"
set "PMO_AUDIT_HOST=http://127.0.0.1:8091"

echo ============================================================
echo PMO AUDITS AND REPORTS
echo Host: %PMO_AUDIT_HOST%
echo Folder: %PMO_DIR%
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PMO_DIR%run_pmo_audits_and_reports.ps1" -HostUrl "%PMO_AUDIT_HOST%" -StartIfOffline

echo.
echo ============================================================
echo PMO audit runner finished.
echo ============================================================
pause
