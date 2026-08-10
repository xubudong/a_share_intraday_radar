$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$Manager = Join-Path $ProjectRoot "manage.py"

if (-not (Test-Path -LiteralPath $ProjectPython)) {
    Write-Error "未找到项目虚拟环境：$ProjectPython"
    exit 1
}

$ManagerArguments = @("`"$Manager`"", "start") + $args
Start-Process `
    -FilePath $ProjectPython `
    -ArgumentList $ManagerArguments `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden
exit 0
