@echo off
rem ===============================================================
rem  shukatsu-calendar : settings window
rem
rem  Opens a window where you can set everything up without
rem  editing any files by hand: the Google key, calendar ID,
rem  which sites to use, logins, test runs and daily scheduling.
rem ===============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] This Python has no tkinter.
    echo         Reinstall Python from python.org and keep
    echo         "tcl/tk and IDLE" ticked in the installer.
    pause
    exit /b 1
)

rem pythonw.exe keeps the black console window from appearing
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "setup_gui.py"
) else (
    ".venv\Scripts\python.exe" "setup_gui.py"
)
