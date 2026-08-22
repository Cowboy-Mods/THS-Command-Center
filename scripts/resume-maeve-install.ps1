[CmdletBinding()]
param(
    [switch]$InstallDocker,
    [string]$InstallerPath = 'C:\THS\Installers\OctoEverywhere\Docker Desktop Installer 4.87.0.exe'
)

$ErrorActionPreference = 'Stop'
$expectedHash = '9AC03D4E900C0FDEE981D4BDE083A55FDFB28FFBA2CAE77726EFF2A437254822'
$preflightScript = Join-Path $PSScriptRoot 'maeve-preflight.ps1'

if (-not (Test-Path -LiteralPath $preflightScript -PathType Leaf)) {
    throw "Maeve preflight script is missing: $preflightScript"
}

$preflightText = & $preflightScript -AsJson 2>$null
$preflightCode = $LASTEXITCODE
$preflight = $preflightText | ConvertFrom-Json
if ($preflightCode -ne 0 -or -not $preflight.SafeToInstallDocker) {
    throw 'Maeve installation is blocked. Run maeve-preflight.ps1 and resolve every reported gate.'
}
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "The staged Docker installer is missing: $InstallerPath"
}
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash
if ($actualHash -ne $expectedHash) {
    throw 'The staged Docker installer hash does not match the approved manifest.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker Inc') {
    throw 'The staged Docker installer signature is not valid for Docker Inc.'
}

if (-not $InstallDocker) {
    Write-Host 'Preflight PASS. Installer signature and hash PASS.'
    Write-Host 'Nothing was installed. Re-run with -InstallDocker only when Cowboy is present.'
    exit 0
}

Write-Host 'Opening the official Docker Desktop installer interactively.'
Write-Host 'Do not enable Kubernetes. Do not sign in. Do not accept a restart.'
$process = Start-Process -FilePath $InstallerPath -PassThru
Wait-Process -Id $process.Id
Write-Host 'Docker installer exited. Stop here for Docker terms/onboarding and any restart gate.'
Write-Host 'Do not configure OctoEverywhere until Cowboy completes account linking and private credential entry.'
exit 3
