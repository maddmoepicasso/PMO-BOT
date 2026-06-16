@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Strict Regime Filter Test
echo ============================================================
echo.
echo Research only. It does not place trades.
echo Compares SPY/QQQ/risk-on market filters across robustness windows.
echo.

python "%PMO_PY%pmo_strict_regime_test.py"

echo.
echo Reports are saved under:
echo %PMO_PY%pmo_reports\backtests\strict_regime
echo.
pause
