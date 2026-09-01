@echo off
rem ===============================================================
rem  shukatsu-calendar : dry run
rem  Shows what would be added to the calendar. Writes nothing.
rem ===============================================================
setlocal
cd /d "%~dp0"
call "run.bat" --dry-run
