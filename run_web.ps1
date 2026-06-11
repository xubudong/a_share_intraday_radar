$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostName = if ($env:WEB_HOST) { $env:WEB_HOST } else { "127.0.0.1" }
$Port = if ($env:WEB_PORT) { $env:WEB_PORT } else { "8030" }
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "py"
}

Write-Host "Starting A Share Intraday Radar at http://$HostName`:$Port"
Set-Location $Root
& $Python -m uvicorn app.server:app --host $HostName --port $Port --reload
