@echo off
rem ===============================================================
rem  shukatsu-calendar : run the sync
rem
rem  Double-click to run, or from a command prompt:
rem      run.bat --dry-run
rem      run.bat --site type_shukatsu
rem      run.bat --list-sites
rem ===============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "main.py" %*
set "RC=%ERRORLEVEL%"

rem Pause only when started by double-click, so scheduled runs
rem never hang waiting for a key press.
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause

exit /b %RC%
