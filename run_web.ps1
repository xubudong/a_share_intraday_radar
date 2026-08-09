$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManagerScript = Join-Path $ProjectRoot "manage.ps1"

& $ManagerScript restart
exit $LASTEXITCODE
