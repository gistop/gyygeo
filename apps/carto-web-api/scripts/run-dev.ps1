. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoWebApiPython
Assert-ProjectPython -PythonExe $PythonExe

$Port = if ($env:GYYGEO_WEB_API_PORT) { [int]$env:GYYGEO_WEB_API_PORT } else { 8020 }
$PortPattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+.*LISTENING\s+(\d+)"
$PortLine = netstat -ano | Select-String -Pattern $PortPattern | Select-Object -First 1

if ($PortLine) {
    $ProcessId = $PortLine.Matches[0].Groups[1].Value
    Write-Output "carto-web-api is already running or port $Port is in use by PID $ProcessId."
    Write-Output "Health: http://127.0.0.1:$Port/health"
    Write-Output "Runtime: http://127.0.0.1:$Port/runtime"
    exit 0
}

Set-Location $Script:ProjectRoot
& $PythonExe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
