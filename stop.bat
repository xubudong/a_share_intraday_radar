@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "stop_services.py" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 "stop_services.py" %*
    exit /b %ERRORLEVEL%
)

python "stop_services.py" %*
exit /b %ERRORLEVEL%
