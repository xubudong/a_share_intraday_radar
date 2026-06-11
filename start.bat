@echo off
setlocal
set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Creating virtual environment in .venv...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        python -m venv "%VENV_DIR%"
    )
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        exit /b 1
    )
)

"%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo Failed to install project dependencies.
    exit /b 1
)

"%PYTHON%" "%ROOT%radar.py" start
exit /b %ERRORLEVEL%
