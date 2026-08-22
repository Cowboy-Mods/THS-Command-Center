[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "status")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$DatabasePath
)

$ErrorActionPreference = "Stop"
$projectPath = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$databasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$runtimePath = Join-Path (Split-Path -Parent $databasePath) "runtime"
$pidFile = Join-Path $runtimePath "ths-dashboard.json"
$dashboardUrl = "http://127.0.0.1:8787"
$expectedApplicationPath = Join-Path $projectPath "inventory\__init__.py"
$bootstrapPath = Join-Path $projectPath "scripts\ths_dashboard_bootstrap.py"
$expectedHost = "127.0.0.1"
$expectedPort = 8787

function Get-THSPython {
    if ($env:THS_PYTHON) {
        $configured = [System.IO.Path]::GetFullPath($env:THS_PYTHON)
        if (Test-Path -LiteralPath $configured -PathType Leaf) {
            return [pscustomobject]@{ FilePath = $configured; PrefixArguments = @() }
        }
        throw "THS_PYTHON points to a missing file: $configured"
    }

    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $resolvedPython = (& $pyLauncher.Source -3 -c "import sys; print(sys.executable)").Trim()
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
            return [pscustomobject]@{ FilePath = $resolvedPython; PrefixArguments = @() }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike "*\WindowsApps\python.exe") {
        return [pscustomobject]@{ FilePath = $python.Source; PrefixArguments = @() }
    }

    $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundled -PathType Leaf) {
        return [pscustomobject]@{ FilePath = $bundled; PrefixArguments = @() }
    }

    throw "Python 3 was not found. Install Python 3 or set THS_PYTHON to python.exe."
}

function Read-THSProcessRecord {
    if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "The THS Dashboard process record is invalid. Nothing was stopped."
    }
}

function Get-VerifiedTHSProcess {
    param($Record)

    if (-not $Record) {
        return $null
    }
    $process = Get-Process -Id ([int]$Record.ProcessId) -ErrorAction SilentlyContinue
    if (-not $process) {
        return $null
    }
    $sameExecutable = (
        [System.IO.Path]::GetFullPath($process.Path) -eq
        [System.IO.Path]::GetFullPath([string]$Record.ExecutablePath)
    )
    $sameStart = $process.StartTime.ToFileTimeUtc() -eq [int64]$Record.StartTimeUtcFileTime
    $sameProject = (
        [System.IO.Path]::GetFullPath([string]$Record.ProjectPath) -eq $projectPath
    )
    $sameDatabase = (
        [System.IO.Path]::GetFullPath([string]$Record.DatabasePath) -eq $databasePath
    )
    $sameApplication = (
        $Record.ApplicationPath -and
        [System.IO.Path]::GetFullPath([string]$Record.ApplicationPath) -eq
        [System.IO.Path]::GetFullPath($expectedApplicationPath)
    )
    $processDetails = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    $commandLine = [string]$processDetails.CommandLine
    $sameCommandLine = (
        $commandLine -and
        $commandLine.Contains($bootstrapPath) -and
        $commandLine.Contains("--database $databasePath") -and
        $commandLine.Contains("serve --host $expectedHost --port $expectedPort")
    )
    $ownsExpectedListener = Get-NetTCPConnection -LocalAddress $expectedHost `
        -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $process.Id }
    if (-not (
        $sameExecutable -and $sameStart -and $sameProject -and
        $sameDatabase -and $sameApplication -and $sameCommandLine -and
        $ownsExpectedListener
    )) {
        throw "Safety check failed: PID, command line, database path, application path, or listener ownership does not match the approved THS Dashboard."
    }
    return $process
}

function Get-VerifiedTHSListenerProcess {
    $listeners = @(Get-NetTCPConnection -LocalAddress $expectedHost `
        -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return $null
    }

    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1) {
        throw "Safety check failed: port $expectedPort has multiple listener owners. Nothing was stopped."
    }

    $process = Get-Process -Id ([int]$owners[0]) -ErrorAction SilentlyContinue
    if (-not $process) {
        throw "Safety check failed: the port $expectedPort listener process could not be inspected. Nothing was stopped."
    }

    $processDetails = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    $commandLine = [string]$processDetails.CommandLine
    $normalizedCommandLine = $commandLine.Replace('"', '')
    $sameExecutable = (
        $process.Path -and
        [System.IO.Path]::GetFileName($process.Path) -ieq "python.exe"
    )
    $sameCommandLine = (
        $normalizedCommandLine -and
        $normalizedCommandLine.Contains($bootstrapPath) -and
        $normalizedCommandLine.Contains("--database $databasePath") -and
        $normalizedCommandLine.Contains("serve --host $expectedHost --port $expectedPort")
    )
    $sameApplication = Test-Path -LiteralPath $expectedApplicationPath -PathType Leaf
    $ownsExpectedListener = $listeners | Where-Object {
        $_.OwningProcess -eq $process.Id
    }

    if (-not (
        $sameExecutable -and $sameCommandLine -and
        $sameApplication -and $ownsExpectedListener
    )) {
        throw "Safety check failed: the port $expectedPort listener is not the approved THS Dashboard. Nothing was stopped."
    }

    return $process
}

function Remove-StaleTHSRecord {
    $record = Read-THSProcessRecord
    if (-not $record) {
        return
    }
    $process = Get-VerifiedTHSProcess $record
    if ($process) {
        throw "THS Dashboard is already running as process $($process.Id)."
    }
    Remove-Item -LiteralPath $pidFile -Force
}

if ($Action -eq "status") {
    $record = Read-THSProcessRecord
    $process = Get-VerifiedTHSProcess $record
    if ($process) {
        Write-Host "THS Dashboard is running as process $($process.Id) at $dashboardUrl"
        exit 0
    }
    Write-Host "THS Dashboard is not running."
    exit 1
}

if ($Action -eq "stop") {
    $record = Read-THSProcessRecord
    $process = $null
    if ($record) {
        $process = Get-VerifiedTHSProcess $record
    }
    if ($record -and -not $process) {
        Remove-Item -LiteralPath $pidFile -Force
        Write-Host "The recorded THS Dashboard process is no longer running."
    }
    if (-not $process) {
        $process = Get-VerifiedTHSListenerProcess
    }
    if (-not $process) {
        Write-Host "THS Dashboard is not running. Nothing was stopped."
        exit 0
    }
    Stop-Process -Id $process.Id -ErrorAction Stop
    Wait-Process -Id $process.Id -ErrorAction SilentlyContinue
    $stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
    $stillListening = Get-NetTCPConnection -LocalAddress $expectedHost `
        -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $process.Id }
    if ($stillRunning -or $stillListening) {
        throw "THS Dashboard process $($process.Id) did not stop cleanly."
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped THS Dashboard process $($process.Id)."
    exit 0
}

if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "THS Inventory database was not found: $databasePath"
}
$existingListener = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
    $owners = @($existingListener | Select-Object -ExpandProperty OwningProcess -Unique)
    throw "THS Dashboard cannot start: port 8787 is already owned by process(es) $($owners -join ', ')."
}
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
Remove-StaleTHSRecord
$python = Get-THSPython
if (-not (Test-Path -LiteralPath $bootstrapPath -PathType Leaf)) {
    throw "THS launcher bootstrap was not found: $bootstrapPath"
}

Push-Location $projectPath
try {
    Write-Host "Preparing the THS Inventory database..."
    & $python.FilePath @($python.PrefixArguments) -I $bootstrapPath --database $databasePath migrate
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed with exit code $LASTEXITCODE."
    }

    $serverArguments = @($python.PrefixArguments) +
        @("-I", $bootstrapPath, "--database", $databasePath,
          "serve", "--host", "127.0.0.1", "--port", "8787")
    $server = Start-Process -FilePath $python.FilePath -ArgumentList $serverArguments `
        -WorkingDirectory $projectPath -NoNewWindow -PassThru
    $record = [ordered]@{
        ProcessId = $server.Id
        StartTimeUtcFileTime = $server.StartTime.ToFileTimeUtc()
        ExecutablePath = $server.Path
        ProjectPath = $projectPath
        DatabasePath = $databasePath
        ApplicationPath = $expectedApplicationPath
        Url = $dashboardUrl
        Host = $expectedHost
        Port = $expectedPort
    }
    $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

    Write-Host "Starting THS Dashboard at $dashboardUrl"
    Write-Host "Keep this window open. Press Ctrl+C or use Stop THS Dashboard.cmd to stop it."
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($server.HasExited) {
            throw "THS Dashboard stopped during startup with exit code $($server.ExitCode)."
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $dashboardUrl -TimeoutSec 1
            $listener = Get-NetTCPConnection -LocalPort 8787 -State Listen `
                -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $server.Id }
            if ($response.StatusCode -ge 200 -and $listener) {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) {
        throw "THS Dashboard did not become ready at $dashboardUrl."
    }

    Start-Process $dashboardUrl
    Wait-Process -Id $server.Id
    $server.Refresh()
    exit $server.ExitCode
}
finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Pop-Location
}
