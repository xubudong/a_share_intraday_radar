@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "start_services.py" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 "start_services.py" %*
    exit /b %ERRORLEVEL%
)

python "start_services.py" %*
exit /b %ERRORLEVEL%
