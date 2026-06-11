@echo off
setlocal
cd /d "%~dp0"

set "VENV_DIR=%CD%\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PID_FILE=%CD%\.radar.pid"
set "STDOUT_LOG=%CD%\.radar.out.log"
set "STDERR_LOG=%CD%\.radar.err.log"

if not defined WEB_HOST set "WEB_HOST=127.0.0.1"
if not defined WEB_PORT set "WEB_PORT=8030"

if exist "%PID_FILE%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$record = Get-Content -LiteralPath '%PID_FILE%' -Raw | ConvertFrom-Json; " ^
        "$process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop; " ^
        "$probeHost = if ([string]$record.host -in @('0.0.0.0', '::')) { '127.0.0.1' } else { [string]$record.host }; " ^
        "$client = [Net.Sockets.TcpClient]::new(); " ^
        "try { $client.Connect($probeHost, [int]$record.port); $listening = $true } catch { $listening = $false } finally { $client.Dispose() }; " ^
        "$started = [datetimeoffset]::Parse([string]$record.start_time_utc).UtcDateTime; " ^
        "$sameStart = [math]::Abs(($process.StartTime.ToUniversalTime() - $started).TotalSeconds) -lt 10; " ^
        "if ($listening -and $sameStart) { exit 0 } else { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo A Share Intraday Radar is already running.
        exit /b 0
    )
    del /q "%PID_FILE%" >nul 2>&1
)

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
        pause
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install project dependencies.
    pause
    exit /b 1
)

del /q "%PID_FILE%" "%STDOUT_LOG%" "%STDERR_LOG%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$probeHost = if ('%WEB_HOST%' -in @('0.0.0.0', '::')) { '127.0.0.1' } else { '%WEB_HOST%' }; " ^
    "$client = [Net.Sockets.TcpClient]::new(); " ^
    "try { $client.Connect($probeHost, [int]'%WEB_PORT%'); exit 1 } catch { exit 0 } finally { $client.Dispose() }"
if errorlevel 1 (
    echo Port %WEB_PORT% is already in use.
    pause
    exit /b 1
)

start "" /b "%PYTHON%" -m app.launcher --host "%WEB_HOST%" --port "%WEB_PORT%" --pid-file "%PID_FILE%" >"%STDOUT_LOG%" 2>"%STDERR_LOG%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pidFile = '%PID_FILE%'; " ^
    "$probeHost = if ('%WEB_HOST%' -in @('0.0.0.0', '::')) { '127.0.0.1' } else { '%WEB_HOST%' }; " ^
    "$port = [int]'%WEB_PORT%'; " ^
    "$deadline = (Get-Date).AddSeconds(20); " ^
    "do { " ^
    "  $record = if (Test-Path -LiteralPath $pidFile) { Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json } else { $null }; " ^
    "  $process = if ($record) { Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue } else { $null }; " ^
    "  $client = [Net.Sockets.TcpClient]::new(); " ^
    "  try { $client.Connect($probeHost, $port); $listening = $true } catch { $listening = $false } finally { $client.Dispose() }; " ^
    "  if (-not $process -or -not $listening) { Start-Sleep -Milliseconds 250 } " ^
    "} while ((-not $process -or -not $listening) -and (Get-Date) -lt $deadline); " ^
    "if (-not $process -or -not $listening) { if ($record) { Stop-Process -Id ([int]$record.pid) -Force -ErrorAction SilentlyContinue }; throw 'Service did not start listening within 20 seconds.' }; " ^
    "Write-Host ('Started A Share Intraday Radar with PID ' + $record.pid + ' at http://%WEB_HOST%:%WEB_PORT%')"

if errorlevel 1 (
    echo Failed to start A Share Intraday Radar.
    pause
    exit /b 1
)

endlocal
