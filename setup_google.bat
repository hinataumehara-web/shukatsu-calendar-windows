@echo off
rem ===============================================================
rem  shukatsu-calendar : optional Google Calendar API support
rem
rem  You only need this if you want the tool to write into your
rem  Google Calendar directly, instead of producing a file you
rem  import (ics.bat). It also needs a Google Cloud service
rem  account - see the README before running this.
rem ===============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Installing Google API libraries ...
".venv\Scripts\python.exe" -m pip install -r requirements-google.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo.
echo Done. Next you still need to:
echo   1. Create a service account in Google Cloud Console
echo   2. Save its JSON key here as service_account.json
echo   3. Share your calendar with the service account address
echo   4. Put your calendar ID in config.yaml
echo See the README - the section about writing to Google Calendar.
echo.
pause
