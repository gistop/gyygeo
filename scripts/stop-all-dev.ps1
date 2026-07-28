$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidFile = Join-Path $Root ".run\dev-services.json"
$Ports = @(8000, 8010, 8020, 5173)

function Get-ListenerProcessId {
    param([int] $Port)

    $PortPattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $PortLine = netstat -ano | Select-String -Pattern $PortPattern | Select-Object -First 1

    if ($PortLine) {
        return [int] $PortLine.Matches[0].Groups[1].Value
    }

    return $null
}

$ProcessIds = New-Object System.Collections.Generic.HashSet[int]

foreach ($Port in $Ports) {
    $ProcessId = Get-ListenerProcessId -Port $Port

    if ($ProcessId) {
        [void] $ProcessIds.Add([int] $ProcessId)
    }
}

if (Test-Path $PidFile) {
    $State = Get-Content -Raw -Path $PidFile | ConvertFrom-Json

    foreach ($Service in $State.services) {
        if ($Service.launcherPid) {
            [void] $ProcessIds.Add([int] $Service.launcherPid)
        }

        if ($Service.listenerPid) {
            [void] $ProcessIds.Add([int] $Service.listenerPid)
        }
    }
}

if ($ProcessIds.Count -eq 0) {
    Write-Output "No dev service processes found on ports 8000, 8010, 8020, or 5173."
    exit 0
}

foreach ($ProcessId in $ProcessIds) {
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue

    if (-not $Process) {
        continue
    }

    Write-Output ("Stopping PID {0} ({1})..." -f $Process.Id, $Process.ProcessName)
    Stop-Process -Id $Process.Id -Force
}

Write-Output "Stopped dev service processes."
