param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Command = "status",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ManagerArguments
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Manager = Join-Path $ProjectRoot "scripts\manage.py"

if (-not (Test-Path -LiteralPath $ProjectPython)) {
    Write-Error "未找到项目虚拟环境：$ProjectPython"
    exit 1
}

& $ProjectPython $Manager $Command @ManagerArguments
exit $LASTEXITCODE
