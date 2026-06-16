@echo off
setlocal
set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PYTHONUTF8=1"
cd /d "%PMO_PY%"
echo ==============================================
echo Starting PMO BOT Auto Command Loop
echo Root: %PMO_ROOT%
echo Python: %PMO_PY%
echo ==============================================
python pmo_bot.py --loop --interval 60
pause
