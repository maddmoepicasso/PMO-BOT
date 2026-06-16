@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Pullback Robustness Test
echo ============================================================
echo.
echo Research only. It does not place trades.
echo Uses yfinance max history so older windows can be judged.
echo.

python "%PMO_PY%pmo_robustness_test.py" --use-yfinance --period max

echo.
echo Reports are saved under:
echo %PMO_PY%pmo_reports\backtests\robustness
echo.
pause
