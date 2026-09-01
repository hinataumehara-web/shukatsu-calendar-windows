@echo off
rem ===============================================================
rem  shukatsu-calendar : first-time setup for Windows
rem
rem  Creates .venv, installs dependencies, downloads Chromium and
rem  prepares .env / config.yaml. Just double-click this file.
rem  (Messages are in English on purpose: the Windows console
rem   garbles Japanese text in .bat files depending on the code page.)
rem ===============================================================
setlocal
cd /d "%~dp0"

rem ---- find a Python 3.10+ interpreter -------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3.10 or newer was not found.
    echo         Download it from https://www.python.org/downloads/windows/
    echo         and tick "Add python.exe to PATH" while installing.
    echo.
    pause
    exit /b 1
)
echo Using interpreter: %PY%
echo.

rem ---- 1. virtual environment ----------------------------------
echo [1/4] Creating virtual environment (.venv) ...
if exist ".venv\Scripts\python.exe" (
    echo       .venv already exists - reusing it.
) else (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
)

rem ---- 2. python packages --------------------------------------
echo [2/4] Installing Python packages ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    echo         If you are behind a company proxy, set HTTPS_PROXY first.
    pause
    exit /b 1
)

rem ---- 3. browser ----------------------------------------------
echo [3/4] Downloading Chromium for Playwright ...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] playwright install failed.
    echo         Antivirus or a proxy may be blocking the download.
    pause
    exit /b 1
)

rem ---- 4. config files -----------------------------------------
echo [4/4] Preparing config files ...
if not exist ".env" copy /y ".env.example" ".env" >nul
if not exist "config.yaml" copy /y "config.example.yaml" "config.yaml" >nul

echo.
echo ============================================================
echo  Setup finished.
echo.
echo  Next steps (see README.md for details):
echo   1. Edit .env         - login e-mail / password for each site
echo   2. Edit config.yaml  - your Google Calendar ID
echo   3. Put service_account.json in this folder
echo   4. Double-click dry_run.bat to check without writing
echo ============================================================
echo.
pause
