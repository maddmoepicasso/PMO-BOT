@echo off
setlocal

set "PMO_ROOT=%~dp0"
set "PMO_PY=%PMO_ROOT%Python"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo PMO PLAYZ YOUTUBE OAUTH REFRESH TOKEN HELPER
echo This opens Google login and saves the refresh token to .env.
echo ============================================================
echo.

if not exist "%PMO_PY%\get_youtube_refresh_token.py" (
    echo ERROR: get_youtube_refresh_token.py was not found.
    echo Expected: "%PMO_PY%\get_youtube_refresh_token.py"
    pause
    exit /b 1
)

python "%PMO_PY%\get_youtube_refresh_token.py"

echo.
echo Done. If the helper succeeded, restart PMO Playz.
pause
