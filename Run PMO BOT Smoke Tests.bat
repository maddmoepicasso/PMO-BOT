@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python -m unittest discover -s tests -p "test_*.py"
endlocal
