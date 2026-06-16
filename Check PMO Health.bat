@echo off
setlocal
set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PYTHONUTF8=1"
cd /d "%PMO_PY%"
echo ==============================================
echo Checking PMO BOT Health
echo Root: %PMO_ROOT%
echo Python: %PMO_PY%
echo ==============================================
python -m py_compile pmo_bot.py pmo_settings.py pmo_bot_loop.py
if errorlevel 1 (
    echo.
    echo PMO BOT compile check failed.
    pause
    exit /b 1
)
python pmo_bot.py --once
pause
