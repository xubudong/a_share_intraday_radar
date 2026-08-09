@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project Python not found: .venv\Scripts\python.exe
    echo Create .venv and install requirements.txt first.
    exit /b 1
)

".venv\Scripts\python.exe" "scripts\manage.py" start %*
exit /b %ERRORLEVEL%
