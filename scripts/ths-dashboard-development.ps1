[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatabasePath
)

$ErrorActionPreference = "Stop"
$projectPath = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$databasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$productionDatabase = [System.IO.Path]::GetFullPath(
    (Join-Path $env:USERPROFILE "Documents\THS-Command-Center-Data\inventory.sqlite3")
)
$developmentPort = 8788
$bootstrapPath = Join-Path $projectPath "scripts\ths_dashboard_bootstrap.py"

if ($databasePath -eq $productionDatabase) {
    throw "Development launcher refuses the production database. Separate authorization is required."
}
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "Explicit development database was not found: $databasePath"
}
$listener = Get-NetTCPConnection -LocalPort $developmentPort -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owners = @($listener | Select-Object -ExpandProperty OwningProcess -Unique)
    throw "THS DEVELOPMENT server cannot start: port $developmentPort is owned by process(es) $($owners -join ', ')."
}

$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Bundled Python was not found: $python"
}

Write-Host "THS DEVELOPMENT dashboard: explicit database $databasePath"
Write-Host "THS DEVELOPMENT port: $developmentPort"
Push-Location $projectPath
try {
    & $python -I $bootstrapPath --database $databasePath serve --host 127.0.0.1 --port $developmentPort
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
