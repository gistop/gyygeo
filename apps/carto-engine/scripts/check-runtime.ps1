. "$PSScriptRoot\_common.ps1"

$PythonExe = Get-GyyGeoCartoPython
Assert-ProjectPython -PythonExe $PythonExe

& $PythonExe --version
& $PythonExe -c "import arcpy; print('ArcPy', arcpy.GetInstallInfo().get('Version')); print('License', arcpy.ProductInfo())"
& $PythonExe -c "import fastapi, pydantic, uvicorn; print('FastAPI', fastapi.__version__); print('Pydantic', pydantic.__version__); print('Uvicorn', uvicorn.__version__)"
