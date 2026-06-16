@echo off
setlocal

set "PMO_PY=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%PMO_PY%"

echo ============================================================
echo PMO Historical Backtest Data Downloader
echo ============================================================
echo.
echo Research only. Downloads daily OHLCV CSV files for backtests.
echo Source priority: Alpaca, Tiingo, Alpha Vantage, yfinance fallback.
echo.

python "%PMO_PY%pmo_historical_data_downloader.py" --source auto --years 5

echo.
echo CSV files are saved under:
echo %PMO_PY%pmo_csv\backtest_daily_bars
echo.
pause
