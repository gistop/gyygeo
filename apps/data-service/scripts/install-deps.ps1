. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoDataPython
Assert-ProjectPython -PythonExe $PythonExe

& $PythonExe -m pip install -r (Join-Path $Script:ProjectRoot "requirements.txt")

