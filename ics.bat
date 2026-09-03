@echo off
rem ===============================================================
rem  shukatsu-calendar : write deadlines to shukatsu.ics
rem
rem  No Google Cloud setup needed. This writes a calendar file
rem  that you import into Google Calendar, Outlook, or Apple
rem  Calendar. Re-importing never creates duplicates, because
rem  every deadline keeps the same event ID.
rem ===============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "main.py" --ics %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Something went wrong. See shukatsu.log for details.
    pause
    exit /b %RC%
)

echo.
set "OPENIT="
set /p "OPENIT=Open the Google Calendar import page now? [Y/n] "
if /i "%OPENIT%"=="n" goto :done
start "" "https://calendar.google.com/calendar/u/0/r/settings/export"
echo Opened your browser. Choose "Import" and pick shukatsu.ics
echo in this folder:
echo   %CD%

:done
echo.
pause
exit /b 0
