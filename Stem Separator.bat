@echo off
rem Starts the Stem Separator GUI without a console window.
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Stem Separator is not installed yet. Run install.bat first.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0stem_gui.py"
