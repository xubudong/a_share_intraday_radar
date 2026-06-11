@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Cannot stop: .venv was not found. Run start.bat first.
    exit /b 1
)

"%PYTHON%" "%ROOT%radar.py" stop
exit /b %ERRORLEVEL%
