$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv，请先运行 start.bat。"
}

Set-Location $Root
& $Python radar.py restart
