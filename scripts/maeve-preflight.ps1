[CmdletBinding()]
param([switch]$AsJson)

$ErrorActionPreference = "Stop"

function Get-FeatureState([string]$Name) {
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop
        return [string]$feature.State
    }
    catch {
        return "UNKNOWN - run from an elevated PowerShell window"
    }
}

function Get-WSLStatus {
    $result = [ordered]@{
        Installed = $false
        Version = $null
        DefaultVersion = $null
        VersionCommandSucceeded = $false
        StatusCommandSucceeded = $false
        Detail = "Not installed"
    }
    try {
        # Modern wsl.exe can emit UTF-16 text that Windows PowerShell captures
        # with embedded NUL characters. Normalize it before parsing.
        $versionOutput = ((& wsl.exe --version 2>&1 | Out-String) -replace [char]0, '').Trim()
        $versionExitCode = $LASTEXITCODE
        $statusOutput = ((& wsl.exe --status 2>&1 | Out-String) -replace [char]0, '').Trim()
        $statusExitCode = $LASTEXITCODE
        $versionMatch = [regex]::Match($versionOutput, '(?im)^WSL version:\s*([^\s]+)')
        $defaultMatch = [regex]::Match($statusOutput, '(?im)^Default Version:\s*([12])\s*$')

        $result.VersionCommandSucceeded = $versionExitCode -eq 0
        $result.StatusCommandSucceeded = $statusExitCode -eq 0
        if ($result.VersionCommandSucceeded -and $versionMatch.Success) {
            $result.Installed = $true
            $result.Version = $versionMatch.Groups[1].Value
            if ($result.StatusCommandSucceeded -and $defaultMatch.Success) {
                $result.DefaultVersion = [int]$defaultMatch.Groups[1].Value
            }
            $result.Detail = "Installed"
        }
    }
    catch {}
    return [pscustomobject]$result
}

function Get-RegistryValue([string]$Path, [string]$Name) {
    try {
        return Get-ItemPropertyValue -LiteralPath $Path -Name $Name -ErrorAction Stop
    }
    catch {
        return $null
    }
}

$processor = Get-CimInstance Win32_Processor | Select-Object -First 1
$computer = Get-CimInstance Win32_ComputerSystem
$wsl = Get-WSLStatus
$sessionManager = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
$pendingRename = @((Get-RegistryValue $sessionManager 'PendingFileRenameOperations'))
$pendingRename2 = @((Get-RegistryValue $sessionManager 'PendingFileRenameOperations2'))
$cbsRebootPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
$windowsUpdateRebootRequired = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
$windowsUpdateServicesPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Services\Pending'
$updateExeVolatile = Get-RegistryValue 'HKLM:\SOFTWARE\Microsoft\Updates' 'UpdateExeVolatile'
$activeComputerName = Get-RegistryValue 'HKLM:\SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName' 'ComputerName'
$configuredComputerName = Get-RegistryValue 'HKLM:\SYSTEM\CurrentControlSet\Control\ComputerName\ComputerName' 'ComputerName'
$computerRenamePending = [bool]($activeComputerName -and $configuredComputerName -and $activeComputerName -ne $configuredComputerName)
$domainJoinPending = (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Netlogon\JoinDomain') -or (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Netlogon\AvoidSpnSet')
$msiInProgress = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\InProgress'
$msiRunOnceEntries = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\RunOnceEntries'
$serverManagerRebootAttempts = Get-RegistryValue 'HKLM:\SOFTWARE\Microsoft\ServerManager' 'CurrentRebootAttempts'

# Pending file operations are reported verbatim, but are not by themselves proof
# that Windows still needs a restart. Stale application cleanup entries can
# survive successful boots. A verified active source below remains blocking.
$pendingReboot = (
    $cbsRebootPending -or
    $windowsUpdateRebootRequired -or
    ([int]$updateExeVolatile -ne 0) -or
    $computerRenamePending -or
    $domainJoinPending -or
    $msiInProgress -or
    $msiRunOnceEntries
)
$dockerPackage = Get-ItemProperty `
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', `
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' `
    -ErrorAction SilentlyContinue | Where-Object DisplayName -eq 'Docker Desktop' | Select-Object -First 1
$dockerService = Get-Service -Name 'com.docker.service' -ErrorAction SilentlyContinue
$bambu = Get-Process -Name 'bambu-studio' -ErrorAction SilentlyContinue | Select-Object -First 1
$c = Get-PSDrive -Name C
$virtualMachinePlatform = Get-FeatureState 'VirtualMachinePlatform'
$wslFeature = Get-FeatureState 'Microsoft-Windows-Subsystem-Linux'
$firmwareVirtualizationVerified = [bool]$processor.VirtualizationFirmwareEnabled
$virtualizationReady = (
    $firmwareVirtualizationVerified -and
    [bool]$computer.HypervisorPresent -and
    $virtualMachinePlatform -eq 'Enabled' -and
    $wslFeature -eq 'Enabled'
)
$wslReady = (
    $wsl.Installed -and
    $wsl.VersionCommandSucceeded -and
    $wsl.StatusCommandSucceeded -and
    $wsl.DefaultVersion -eq 2
)
$safeToInstallDocker = (
    $virtualizationReady -and
    $wslReady -and
    -not $pendingReboot -and
    -not $dockerPackage
)

$report = [ordered]@{
    CheckedAt = (Get-Date).ToUniversalTime().ToString('o')
    FirmwareVirtualizationEnabled = $firmwareVirtualizationVerified
    VMMonitorModeExtensions = [bool]$processor.VMMonitorModeExtensions
    SLAT = [bool]$processor.SecondLevelAddressTranslationExtensions
    HypervisorPresent = [bool]$computer.HypervisorPresent
    VirtualizationReady = [bool]$virtualizationReady
    WSLInstalled = [bool]$wsl.Installed
    WSLVersion = $wsl.Version
    WSLDefaultVersion = $wsl.DefaultVersion
    WSLVersionCommandSucceeded = [bool]$wsl.VersionCommandSucceeded
    WSLStatusCommandSucceeded = [bool]$wsl.StatusCommandSucceeded
    WSLReady = [bool]$wslReady
    WSLFeature = $wslFeature
    VirtualMachinePlatform = $virtualMachinePlatform
    HyperV = Get-FeatureState 'Microsoft-Hyper-V-All'
    CBSRebootPending = [bool]$cbsRebootPending
    WindowsUpdateRebootRequired = [bool]$windowsUpdateRebootRequired
    WindowsUpdateServicesPending = [bool]$windowsUpdateServicesPending
    PendingFileRenameOperations = @($pendingRename | Where-Object { $_ })
    PendingFileRenameOperations2 = @($pendingRename2 | Where-Object { $_ })
    PendingFileOperationsAdvisory = [bool](($pendingRename | Where-Object { $_ }).Count -or ($pendingRename2 | Where-Object { $_ }).Count)
    UpdateExeVolatile = if ($null -eq $updateExeVolatile) { 0 } else { [int]$updateExeVolatile }
    ComputerRenamePending = [bool]$computerRenamePending
    DomainJoinPending = [bool]$domainJoinPending
    MSIInProgress = [bool]$msiInProgress
    MSIRunOnceEntries = [bool]$msiRunOnceEntries
    ServerManagerCurrentRebootAttempts = $serverManagerRebootAttempts
    PendingReboot = [bool]$pendingReboot
    DockerInstalled = [bool]$dockerPackage
    DockerVersion = if ($dockerPackage) { $dockerPackage.DisplayVersion } else { $null }
    DockerService = if ($dockerService) { [string]$dockerService.Status } else { 'Not installed' }
    FreeDiskGB = [math]::Round($c.Free / 1GB, 1)
    MemoryGB = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
    BambuStudioRunning = [bool]$bambu
    BambuStudioResponding = if ($bambu) { [bool]$bambu.Responding } else { $false }
    LANModeDecision = 'KEEP OFF - do not change printer networking during setup'
    SafeToInstallDocker = [bool]$safeToInstallDocker
    SafeToContinue = [bool]$safeToInstallDocker
}

if ($AsJson) {
    [pscustomobject]$report | ConvertTo-Json -Depth 3
}
else {
    [pscustomobject]$report | Format-List
    if (-not $safeToInstallDocker) {
        Write-Warning 'Docker installation must not continue. Resolve virtualization, WSL, feature, pending-reboot, or existing-installation gates first.'
    }
}

if ($safeToInstallDocker) { exit 0 } else { exit 2 }
