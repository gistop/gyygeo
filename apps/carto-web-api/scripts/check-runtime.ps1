. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoWebApiPython
Assert-ProjectPython -PythonExe $PythonExe

& $PythonExe --version
& $PythonExe -c "import fastapi, uvicorn; print('fastapi', fastapi.__version__); print('uvicorn', uvicorn.__version__)"
