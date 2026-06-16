@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Pullback Backtest
echo ============================================================
echo.
echo This is research only. It does not place trades.
echo.
echo Running yfinance mode. If yfinance is missing, run:
echo pip install yfinance
echo.

python "%PMO_PY%pmo_pullback_backtest.py" --use-yfinance --period 2y

echo.
echo Reports are saved under:
echo %PMO_PY%pmo_reports\backtests
echo.
pause
