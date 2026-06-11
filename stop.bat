@echo off
setlocal
cd /d "%~dp0"

set "PID_FILE=%CD%\.radar.pid"

if not exist "%PID_FILE%" (
    echo A Share Intraday Radar is not running: PID file not found.
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$root = (Get-Location).Path; " ^
    "$pidFile = Join-Path $root '.radar.pid'; " ^
    "try { $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json } catch { Remove-Item -LiteralPath $pidFile -Force; Write-Error 'Invalid PID file removed.'; exit 1 }; " ^
    "$process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue; " ^
    "if (-not $process) { Remove-Item -LiteralPath $pidFile -Force; Write-Host 'Process is already stopped; stale PID file removed.'; exit 0 }; " ^
    "$started = [datetimeoffset]::Parse([string]$record.start_time_utc).UtcDateTime; " ^
    "$sameStart = [math]::Abs(($process.StartTime.ToUniversalTime() - $started).TotalSeconds) -lt 10; " ^
    "if (-not $sameStart) { Remove-Item -LiteralPath $pidFile -Force; Write-Error 'PID identity mismatch; refusing to stop the process.'; exit 1 }; " ^
    "Stop-Process -Id ([int]$record.pid) -Force; " ^
    "Remove-Item -LiteralPath $pidFile -Force; " ^
    "Write-Host ('Stopped A Share Intraday Radar PID ' + $record.pid)"

if errorlevel 1 (
    pause
    exit /b 1
)

endlocal
