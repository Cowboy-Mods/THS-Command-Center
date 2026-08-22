param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverScript = Join-Path $PSScriptRoot 'maeve_console.py'
$bridgeScript = Join-Path $PSScriptRoot 'maeve_farm_manager_bridge.py'
$farmManagerExe = 'C:\Program Files\Bambu Farm Manager Client\Bambu Farm Manager Client.exe'
$runtime = Join-Path $env:USERPROFILE 'Documents\THS-Command-Center-Data\runtime'
$pidFile = Join-Path $runtime 'maeve-console.pid'
$stopSignal = Join-Path $runtime 'maeve-console.stop'
$bridgePidFile = Join-Path $runtime 'maeve-farm-manager-bridge.pid'
$bridgeStopSignal = Join-Path $runtime 'maeve-farm-manager-bridge.stop'
$farmManagerPidFile = Join-Path $runtime 'maeve-farm-manager-client.pid'
$telemetryState = Join-Path $runtime 'maeve-telemetry.json'
$rainmeterFeed = Join-Path $env:USERPROFILE 'Documents\Rainmeter\Skins\THS\CommandCenter\Bambu\BambuStatus.txt'
$debugPort = 9223
$consoleUrl = 'http://127.0.0.1:48176/'

function Get-MaeveProcess {
    $savedPid = 0
    if ((Test-Path -LiteralPath $pidFile) -and [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$savedPid)) {
        $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        $details = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -match '^python' -and $details -and $details.CommandLine -like "*$serverScript*") { return $process }
    }
    $matches = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object CommandLine -like "*$serverScript*")
    if ($matches.Count -ne 1) { return $null }
    return Get-Process -Id $matches[0].ProcessId -ErrorAction SilentlyContinue
}

function Get-ConsoleListener {
    return Get-NetTCPConnection -State Listen -LocalPort 48176 -ErrorAction SilentlyContinue
}

function Get-SavedProcess([string]$Path, [string]$CommandFragment) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $savedPid = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $Path -Raw).Trim(), [ref]$savedPid)) { return $null }
    $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
    if ($null -eq $details -or $details.CommandLine -notlike "*$CommandFragment*") { return $null }
    return $process
}

function Test-LoopbackPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(500) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Stop-ExactProcessTree([int]$RootPid) {
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object ParentProcessId -eq $RootPid)
    foreach ($child in $children) { Stop-ExactProcessTree -RootPid $child.ProcessId }
    Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Stop-FarmManagerClient {
    $saved = Get-SavedProcess $farmManagerPidFile '--remote-debugging-port=9223'
    if ($saved) {
        $saved.CloseMainWindow() | Out-Null
        $saved.WaitForExit(3000) | Out-Null
        if (-not $saved.HasExited) { Stop-ExactProcessTree -RootPid $saved.Id }
    }
    Remove-Item -LiteralPath $farmManagerPidFile -Force -ErrorAction SilentlyContinue
}

function Find-Python {
    $uvRoot = Join-Path $env:APPDATA 'uv\python'
    $candidate = Get-ChildItem -LiteralPath $uvRoot -Directory -Filter 'cpython-*-windows-x86_64-none' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'python.exe' } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ($candidate) { return $candidate }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'A compatible local Python runtime was not found.'
}

if ($Action -eq 'status') {
    $process = Get-MaeveProcess
    $listener = Get-ConsoleListener
    $bridge = Get-SavedProcess $bridgePidFile $bridgeScript
    $farm = Get-SavedProcess $farmManagerPidFile '--remote-debugging-port=9223'
    if ($process -and $listener.LocalAddress -eq '127.0.0.1' -and $listener.OwningProcess -eq $process.Id -and $bridge -and $farm -and (Test-LoopbackPort $debugPort)) { Write-Host "Maeve console and Farm Manager bridge are running locally at $consoleUrl"; exit 0 }
    Write-Host 'Maeve console is stopped.'
    exit 1
}

if ($Action -eq 'start') {
    $existing = Get-MaeveProcess
    $listener = Get-ConsoleListener
    $existingBridge = Get-SavedProcess $bridgePidFile $bridgeScript
    $existingFarm = Get-SavedProcess $farmManagerPidFile '--remote-debugging-port=9223'
    if ($existing -and $listener.LocalAddress -eq '127.0.0.1' -and $listener.OwningProcess -eq $existing.Id -and $existingBridge -and $existingFarm -and (Test-LoopbackPort $debugPort)) { Write-Host "Maeve console and Farm Manager bridge are already running locally at $consoleUrl"; exit 0 }
    if ($listener) { throw 'Port 48176 is already owned by another process. Maeve was not started.' }
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    Remove-Item -LiteralPath $stopSignal -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $bridgeStopSignal -Force -ErrorAction SilentlyContinue
    $python = Find-Python
    if (-not (Test-Path -LiteralPath $farmManagerExe)) { throw 'Bambu Farm Manager Client is not installed at the verified path.' }
    $otherFarmManager = Get-Process -Name 'Bambu Farm Manager Client' -ErrorAction SilentlyContinue
    if ($otherFarmManager) {
        foreach ($item in $otherFarmManager) { $item.CloseMainWindow() | Out-Null }
        Start-Sleep -Milliseconds 1200
        foreach ($item in $otherFarmManager) { if (-not $item.HasExited) { Stop-ExactProcessTree -RootPid $item.Id } }
    }
    $farmProcess = Start-Process -FilePath $farmManagerExe -WindowStyle Minimized -ArgumentList @('--remote-debugging-address=127.0.0.1', "--remote-debugging-port=$debugPort") -PassThru
    [System.IO.File]::WriteAllText($farmManagerPidFile, [string]$farmProcess.Id, [System.Text.Encoding]::ASCII)
    $debugReady = $false
    for ($index = 0; $index -lt 40; $index++) {
        if (Test-LoopbackPort $debugPort) { $debugReady = $true; break }
        if ($farmProcess.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $debugReady) { Stop-FarmManagerClient; throw 'Farm Manager did not open its loopback-only bridge port.' }
    $bridge = Start-Process -FilePath $python -WindowStyle Hidden -WorkingDirectory $projectRoot -ArgumentList @($bridgeScript, '--debug-url', "http://127.0.0.1:$debugPort", '--state', $telemetryState, '--rainmeter-feed', $rainmeterFeed, '--timeout', '70', '--watch', '--stop-signal', $bridgeStopSignal) -PassThru
    [System.IO.File]::WriteAllText($bridgePidFile, [string]$bridge.Id, [System.Text.Encoding]::ASCII)
    $process = Start-Process -FilePath $python -WindowStyle Hidden -WorkingDirectory $projectRoot -ArgumentList @($serverScript, '--host', '127.0.0.1', '--port', '48176', '--stop-signal', $stopSignal) -PassThru
    [System.IO.File]::WriteAllText($pidFile, [string]$process.Id, [System.Text.Encoding]::ASCII)
    Start-Sleep -Milliseconds 1000
    if ($process.HasExited) { Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue; throw 'Maeve console exited during startup.' }
    $listener = Get-ConsoleListener
    if (-not $listener -or $listener.LocalAddress -ne '127.0.0.1' -or $listener.OwningProcess -ne $process.Id) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Stop-Process -Id $bridge.Id -Force -ErrorAction SilentlyContinue
        Stop-FarmManagerClient
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        throw 'Maeve console did not acquire the verified loopback listener.'
    }
    Write-Host "Maeve console and read-only Farm Manager bridge started locally at $consoleUrl"
    exit 0
}

$process = Get-MaeveProcess
if (-not $process -and -not (Get-SavedProcess $bridgePidFile $bridgeScript) -and -not (Get-SavedProcess $farmManagerPidFile '--remote-debugging-port=9223')) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host 'Maeve console is already stopped.'
    exit 0
}
[System.IO.File]::WriteAllText($stopSignal, 'stop', [System.Text.Encoding]::ASCII)
$bridgeProcess = Get-SavedProcess $bridgePidFile $bridgeScript
[System.IO.File]::WriteAllText($bridgeStopSignal, 'stop', [System.Text.Encoding]::ASCII)
if ($process) {
    $process.WaitForExit(8000) | Out-Null
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(3000) | Out-Null
    }
}
if ($bridgeProcess) {
    $bridgeProcess.WaitForExit(3000) | Out-Null
    if (-not $bridgeProcess.HasExited) { Stop-Process -Id $bridgeProcess.Id -Force }
}
Stop-FarmManagerClient
$listener = Get-ConsoleListener
if ($listener) { throw 'Maeve console process stopped but port 48176 is still occupied.' }
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stopSignal -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $bridgeStopSignal -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $bridgePidFile -Force -ErrorAction SilentlyContinue
Write-Host 'Maeve console and Farm Manager bridge stopped.'
