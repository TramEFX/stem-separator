@echo off
rem Sets up Stem Separator: finds Python 3.12 and runs install.py (optional argument: target key, e.g. amd-rx9070).
setlocal
cd /d "%~dp0"
set "PYTHON="
where uv >nul 2>nul
if not errorlevel 1 (
    uv python find 3.12 >nul 2>nul || uv python install 3.12
    for /f "delims=" %%p in ('uv python find 3.12 2^>nul') do set PYTHON="%%p"
)
if not defined PYTHON (
    py -3.12 -c "import sys" >nul 2>nul && set "PYTHON=py -3.12"
)
if not defined PYTHON (
    echo Python 3.12 was not found.
    echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
    pause
    exit /b 1
)
%PYTHON% "%~dp0install.py" %*
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
