. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoDataPython
Assert-ProjectPython -PythonExe $PythonExe

Set-Location $Script:ProjectRoot
& $PythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8010

