@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Pullback Research Grid
echo ============================================================
echo.
echo This is research only. It does not place trades.
echo It runs the practical grid across full/default, index-tech,
echo and sector ETF universes with the SPY 200MA market filter.
echo.

python "%PMO_PY%pmo_pullback_backtest.py" --use-yfinance --period 2y --grid

echo.
echo Reports are saved under:
echo %PMO_PY%pmo_reports\backtests\research_grid
echo.
pause
