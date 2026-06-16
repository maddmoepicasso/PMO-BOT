@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Pullback Signal Smoke Test
echo ============================================================
echo.
echo Research only. It does not place trades.
echo.

python "%PMO_PY%pmo_pullback_signal.py"

echo.
pause
