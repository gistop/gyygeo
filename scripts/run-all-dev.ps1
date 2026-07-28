$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunDir = Join-Path $Root ".run"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "dev-services.json"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Services = @(
    @{
        Name = "carto-engine"
        Port = 8000
        Url = "http://127.0.0.1:8000/health"
        WorkingDirectory = Join-Path $Root "apps\carto-engine"
        Script = Join-Path $Root "apps\carto-engine\scripts\run-dev.ps1"
    },
    @{
        Name = "data-service"
        Port = 8010
        Url = "http://127.0.0.1:8010/health"
        WorkingDirectory = Join-Path $Root "apps\data-service"
        Script = Join-Path $Root "apps\data-service\scripts\run-dev.ps1"
    },
    @{
        Name = "carto-web-api"
        Port = 8020
        Url = "http://127.0.0.1:8020/health"
        WorkingDirectory = Join-Path $Root "apps\carto-web-api"
        Script = Join-Path $Root "apps\carto-web-api\scripts\run-dev.ps1"
    },
    @{
        Name = "carto-web"
        Port = 5173
        Url = "http://127.0.0.1:5173/"
        WorkingDirectory = Join-Path $Root "apps\carto-web"
        Command = "npm.cmd run dev"
    }
)

function ConvertTo-CmdQuoted {
    param([string] $Value)

    return '"' + ($Value -replace '"', '\"') + '"'
}

function Get-ListenerProcessId {
    param([int] $Port)

    $PortPattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $PortLine = netstat -ano | Select-String -Pattern $PortPattern | Select-Object -First 1

    if ($PortLine) {
        return [int] $PortLine.Matches[0].Groups[1].Value
    }

    return $null
}

$Started = @()
$Existing = @()

foreach ($Service in $Services) {
    $ExistingPid = Get-ListenerProcessId -Port $Service.Port

    if ($ExistingPid) {
        Write-Output ("{0} already appears to be running on port {1} (PID {2})." -f $Service.Name, $Service.Port, $ExistingPid)
        $Existing += [pscustomobject]@{
            name = $Service.Name
            port = $Service.Port
            pid = $ExistingPid
            url = $Service.Url
            status = "already-running"
        }
        continue
    }

    $Log = Join-Path $LogDir ("{0}.log" -f $Service.Name)
    $LogArgument = ConvertTo-CmdQuoted -Value $Log

    "" | Set-Content -Path $Log

    if ($Service.Script) {
        $ScriptArgument = ConvertTo-CmdQuoted -Value $Service.Script
        $CommandLine = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptArgument > $LogArgument 2>&1"
    } else {
        $CommandLine = "$($Service.Command) > $LogArgument 2>&1"
    }

    $Process = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList @("/d", "/c", $CommandLine) `
        -WorkingDirectory $Service.WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru

    Write-Output ("Started {0} launcher as PID {1}; waiting for port {2}..." -f $Service.Name, $Process.Id, $Service.Port)

    $ListeningPid = $null
    $Deadline = (Get-Date).AddSeconds(20)

    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 500
        $ListeningPid = Get-ListenerProcessId -Port $Service.Port

        if ($ListeningPid) {
            break
        }

        if ($Process.HasExited) {
            break
        }
    }

    $Status = if ($ListeningPid) { "running" } else { "starting-or-failed" }
    $Started += [pscustomobject]@{
        name = $Service.Name
        port = $Service.Port
        launcherPid = $Process.Id
        listenerPid = $ListeningPid
        url = $Service.Url
        log = $Log
        status = $Status
    }

    if ($ListeningPid) {
        Write-Output ("{0} is listening at {1} (PID {2})." -f $Service.Name, $Service.Url, $ListeningPid)
    } else {
        Write-Warning ("{0} did not open port {1} within 20 seconds. Check logs in {2}." -f $Service.Name, $Service.Port, $LogDir)
    }
}

$State = [pscustomobject]@{
    startedAt = (Get-Date).ToString("o")
    services = @($Existing + $Started)
}

$State | ConvertTo-Json -Depth 5 | Set-Content -Path $PidFile

Write-Output ""
Write-Output "Service URLs:"
foreach ($Service in $Services) {
    Write-Output ("- {0}: {1}" -f $Service.Name, $Service.Url)
}
Write-Output ""
Write-Output ("State file: {0}" -f $PidFile)
Write-Output ("Logs: {0}" -f $LogDir)
