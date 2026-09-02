@echo off
rem ===============================================================
rem  shukatsu-calendar : save a login session
rem
rem  Opens a real browser window so you can log in by hand
rem  (including any 2-factor code). The logged-in state is saved
rem  to .sessions\<slug>.json and reused by later runs.
rem
rem      login.bat mynavi
rem      login.bat rikunabi
rem
rem  Double-clicking also works - you will be asked for the slug.
rem ===============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

set "SLUG=%~1"
if "%SLUG%"=="" set /p "SLUG=Site slug (mynavi / rikunabi): "
if "%SLUG%"=="" (
    echo No slug given.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "main.py" --login "%SLUG%"
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
